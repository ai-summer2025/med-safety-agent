"""CDS Hooks 2.0 request authentication (JWT bearer tokens signed by the CDS Client).

Per the spec the token header carries alg, kid and typ ("JWT") and optionally jku; the
payload carries iss, aud (the URL of the service endpoint being called), exp, iat and jti.
Symmetric algorithms and "none" are not allowed; ES384 and RS384 are recommended.

Trust is configured per issuer: MEDSAFE_TRUSTED_ISSUERS='{"<iss>": "<jwks url>"}'.
A jku in the token is only honoured when it equals the configured JWKS URL for that
issuer, so a token cannot point the service at a key set of its own choosing.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import jwt

ALLOWED_ALGS = ["ES384", "RS384", "ES256", "RS256", "ES512", "RS512", "PS384"]
MAX_LIFETIME = 300  # seconds; the spec advises short-lived tokens (at most 5 minutes)


class AuthError(Exception):
    pass


def http_jwks(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


@dataclass
class Verifier:
    trusted: Dict[str, str]  # iss -> jwks url
    fetch_jwks: Callable[[str], dict] = http_jwks
    leeway: int = 30
    _cache: Dict[str, tuple] = field(default_factory=dict)
    _seen_jti: Dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _keys(self, url: str) -> dict:
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
        jwks = self.fetch_jwks(url)
        self._cache[url] = (time.time(), jwks)
        return jwks

    def verify(self, authorization: Optional[str], audience: str) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise AuthError(f"malformed token: {e}") from e
        if header.get("typ", "JWT").upper() != "JWT" or header.get("alg") not in ALLOWED_ALGS:
            raise AuthError(f"algorithm {header.get('alg')} not allowed")
        iss = claims.get("iss")
        if iss not in self.trusted:
            raise AuthError(f"untrusted issuer {iss}")
        jwks_url = self.trusted[iss]
        if header.get("jku") and header["jku"] != jwks_url:
            raise AuthError("jku does not match the configured key set for this issuer")
        keys = self._keys(jwks_url).get("keys", [])
        kid = header.get("kid")
        match = [k for k in keys if k.get("kid") == kid] if kid else keys
        if not match:
            raise AuthError(f"no key with kid {kid}")
        try:
            key = jwt.PyJWK(match[0], algorithm=header["alg"]).key
            claims = jwt.decode(token, key=key, algorithms=[header["alg"]], audience=audience, issuer=iss,
                                leeway=self.leeway, options={"require": ["iss", "aud", "exp", "iat", "jti"]})
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid token: {e}") from e
        if claims["exp"] - claims["iat"] > MAX_LIFETIME + self.leeway:
            raise AuthError("token lifetime exceeds 5 minutes")
        with self._lock:
            now = time.time()
            self._seen_jti = {j: t for j, t in self._seen_jti.items() if t > now}
            if claims["jti"] in self._seen_jti:
                raise AuthError("token replay (jti already used)")
            self._seen_jti[claims["jti"]] = claims["exp"] + self.leeway
        return claims
