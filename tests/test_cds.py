import copy
import json
import time
import uuid
from datetime import date
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from medsafe.cds.app import Settings, create_app
from medsafe.cds.auth import Verifier

ROOT = Path(__file__).resolve().parents[1]
REQUEST = json.loads((ROOT / "data/fhir/order_sign_request.json").read_text())
ISS, JWKS_URL, BASE = "https://ehr.example.org", "https://ehr.example.org/.well-known/jwks.json", "http://testserver"
KEY = ec.generate_private_key(ec.SECP384R1())
JWK = {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())), "kid": "k1", "alg": "ES384"}


def token(aud=f"{BASE}/cds-services/medsafe-order-sign", iss=ISS, kid="k1", lifetime=60, jti=None, **extra_headers):
    now = int(time.time())
    return jwt.encode({"iss": iss, "aud": aud, "iat": now, "exp": now + lifetime, "jti": jti or str(uuid.uuid4())},
                      KEY, algorithm="ES384", headers={"kid": kid, "typ": "JWT", **extra_headers})


@pytest.fixture
def client(tmp_path):
    settings = Settings(auth_required=True, trusted_issuers={ISS: JWKS_URL}, audit_log=tmp_path / "audit.jsonl")
    verifier = Verifier(settings.trusted_issuers, fetch_jwks=lambda url: {"keys": [JWK]})
    app = create_app(settings, verifier=verifier, today=lambda: date(2026, 6, 1),
                     fhir_fetcher=lambda *a: (_ for _ in ()).throw(AssertionError("unexpected FHIR fetch")))
    c = TestClient(app)
    c.audit_log = settings.audit_log
    return c


def post(client, body, service="medsafe-order-sign", tok=None):
    tok = tok or token(aud=f"{BASE}/cds-services/{service}")
    return client.post(f"/cds-services/{service}", json=body, headers={"Authorization": f"Bearer {tok}"})


def test_discovery_lists_both_hooks_with_prefetch(client):
    services = {s["id"]: s for s in client.get("/cds-services").json()["services"]}
    assert services["medsafe-order-sign"]["hook"] == "order-sign"
    assert services["medsafe-patient-view"]["hook"] == "patient-view"
    assert "{{context.patientId}}" in services["medsafe-order-sign"]["prefetch"]["medications"]


def test_order_sign_cards_only_concern_the_new_order(client):
    r = post(client, REQUEST)
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]
    rules = {c["source"]["topic"]["code"] for c in cards if "topic" in c["source"]}
    # naproxen + warfarin, naproxen + eGFR 27, naproxen in an 80-year-old ...
    assert {"DDI-ANTICOAG-NSAID", "RENAL-NSAID-30", "BEERS-NSAID"} <= rules
    # ... but nothing about the pre-existing metformin problem: that belongs to patient-view
    assert "RENAL-METFORMIN-30" not in rules
    for c in cards:
        assert len(c["summary"]) < 140 and c["indicator"] in ("info", "warning", "critical") and c["source"]["label"]


def test_major_order_cards_offer_removal_of_the_draft(client):
    cards = post(client, REQUEST).json()["cards"]
    ddi = next(c for c in cards if c.get("source", {}).get("topic", {}).get("code") == "DDI-ANTICOAG-NSAID")
    action = ddi["suggestions"][0]["actions"][0]
    assert action == {"type": "delete", "description": "Remove draft order for naproxen",
                      "resourceId": "MedicationRequest/draft-naproxen"}
    assert ddi["selectionBehavior"] == "at-most-one"
    assert all(o["display"] for o in ddi["overrideReasons"])
    renal = next(c for c in cards if c.get("source", {}).get("topic", {}).get("code") == "RENAL-NSAID-30")
    assert "eGFR used:** 27.0" in renal["detail"]


def test_order_sign_without_drafts_returns_no_cards(client):
    body = copy.deepcopy(REQUEST)
    del body["context"]["draftOrders"]
    assert post(client, body).json() == {"cards": []}


def test_patient_view_reviews_the_whole_list(client):
    body = {**copy.deepcopy(REQUEST), "hook": "patient-view"}
    del body["context"]["draftOrders"]
    cards = post(client, body, service="medsafe-patient-view").json()["cards"]
    codes = {c["source"].get("topic", {}).get("code") for c in cards}
    assert "RENAL-METFORMIN-30" in codes
    assert any("lower-priority medication review item" in c["summary"] for c in cards)
    assert any("homeMedications" in c["detail"] for c in cards if c["summary"].startswith("Medication safety check"))


def test_null_prefetch_means_no_data_not_fetch(client):
    body = copy.deepcopy(REQUEST)
    body["prefetch"]["allergies"] = None
    assert post(client, body).status_code == 200


def test_missing_required_prefetch_without_fhir_access_is_412(client):
    body = copy.deepcopy(REQUEST)
    del body["prefetch"]["medications"]
    assert post(client, body).status_code == 412


def test_missing_prefetch_is_fetched_when_fhir_access_is_given(tmp_path):
    calls = []

    def fetcher(base, query, tok):
        calls.append((base, query, tok))
        return [REQUEST["prefetch"]["medications"]]

    app = create_app(Settings(auth_required=False, audit_log=tmp_path / "a.jsonl"), fhir_fetcher=fetcher,
                     today=lambda: date(2026, 6, 1))
    body = copy.deepcopy(REQUEST)
    del body["prefetch"]["medications"]
    body["fhirServer"], body["fhirAuthorization"] = "https://fhir.example.org/r4", {"access_token": "abc"}
    r = TestClient(app).post("/cds-services/medsafe-order-sign", json=body)
    assert r.status_code == 200
    assert calls == [("https://fhir.example.org/r4",
                      f"MedicationRequest?patient={REQUEST['context']['patientId']}&status=active", "abc")]


@pytest.mark.parametrize("bad", [
    None, "Bearer not-a-jwt", f"Bearer {token(iss='https://evil.example')}",
    f"Bearer {token(aud='https://other.example/cds-services/medsafe-order-sign')}",
    f"Bearer {token(kid='unknown')}", f"Bearer {token(lifetime=3600)}",
    f"Bearer {token(jku='https://evil.example/jwks.json')}",
])
def test_bad_tokens_are_rejected(client, bad):
    headers = {"Authorization": bad} if bad else {}
    assert client.post("/cds-services/medsafe-order-sign", json=REQUEST, headers=headers).status_code == 401


def test_symmetric_algorithms_are_rejected(client):
    now = int(time.time())
    hs = jwt.encode({"iss": ISS, "aud": f"{BASE}/cds-services/medsafe-order-sign", "iat": now, "exp": now + 60,
                     "jti": "x"}, "secret", algorithm="HS256", headers={"kid": "k1"})
    assert post(client, REQUEST, tok=hs).status_code == 401


def test_token_replay_is_rejected(client):
    tok = token(jti="same")
    assert post(client, REQUEST, tok=tok).status_code == 200
    assert post(client, REQUEST, tok=tok).status_code == 401


def test_feedback_is_logged_without_patient_identifiers(client):
    card = post(client, REQUEST).json()["cards"][0]
    fb = {"feedback": [{"card": card["uuid"], "outcome": "overridden", "outcomeTimestamp": "2026-06-01T10:00:00Z",
                        "overrideReason": {"reason": {"code": "will-monitor", "system": "x", "display": "y"}}}]}
    fb_tok = token(aud=f"{BASE}/cds-services/medsafe-order-sign/feedback")
    r = client.post("/cds-services/medsafe-order-sign/feedback", json=fb, headers={"Authorization": f"Bearer {fb_tok}"})
    assert r.status_code == 200
    log = client.audit_log.read_text()
    events = [json.loads(line) for line in log.splitlines()]
    assert events[-1] == {**events[-1], "event": "feedback", "card": card["uuid"], "outcome": "overridden",
                          "overrideReason": "will-monitor"}
    assert REQUEST["context"]["patientId"] not in log


def test_wrong_hook_and_unknown_service(client):
    assert post(client, {**REQUEST, "hook": "patient-view"}).status_code == 400
    assert client.post("/cds-services/nope", json=REQUEST).status_code == 404
