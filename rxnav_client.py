"""
NIH NLM RxNav API client for drug-drug interaction checking.
Free public API — no key required.
Docs: https://rxnav.nlm.nih.gov/InteractionAPIs.html
"""
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

RXNAV_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
REQUEST_DELAY = 0.3


class RxNavClient:
    """Client for the NIH RxNav Drug Interaction API."""

    def __init__(self, request_delay: float = REQUEST_DELAY, _mock_responses: Optional[Dict] = None):
        self.request_delay = request_delay
        self._mock_responses = _mock_responses
        self._call_count = 0

    def _get(self, path: str) -> Dict[str, Any]:
        """Make a GET request to the RxNav API."""
        self._call_count += 1

        if self._mock_responses is not None:
            return self._mock_responses.get(path, {})

        url = f"{RXNAV_BASE_URL}{path}"
        logger.debug(f"RxNav API GET: {url}")

        try:
            time.sleep(self.request_delay)
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"RxNav API error for {path}: {e}")
            return {}

    def find_rxcui(self, drug_name: str) -> Optional[str]:
        """
        Find the RxNorm Concept Unique Identifier (RxCUI) for a drug name.
        Returns None if not found.
        """
        encoded = urllib.parse.quote(drug_name)
        data = self._get(f"/rxcui.json?name={encoded}&search=0")

        id_group = data.get("idGroup", {})
        rxnorm_id = id_group.get("rxnormId", [])
        if rxnorm_id:
            return str(rxnorm_id[0])

        # Try approximate search
        data2 = self._get(f"/approximateTerm.json?term={encoded}&maxEntries=1&option=0")
        candidates = data2.get("approximateGroup", {}).get("candidate", [])
        if candidates:
            return str(candidates[0].get("rxcui", ""))
        return None

    def get_interactions_by_rxcui(self, rxcui: str) -> List[Dict[str, Any]]:
        """Get all known drug interactions for a given RxCUI."""
        data = self._get(f"/interaction/interaction.json?rxcui={rxcui}")
        interaction_type_group = data.get("interactionTypeGroup", [])

        interactions = []
        for group in interaction_type_group:
            for itype in group.get("interactionType", []):
                for pair in itype.get("interactionPair", []):
                    interactions.append({
                        "severity": pair.get("severity", "N/A"),
                        "description": pair.get("description", ""),
                        "concepts": pair.get("interactionConcept", []),
                    })
        return interactions

    def get_interaction_between_pair(
        self, rxcui_a: str, rxcui_b: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check interaction between two specific drugs by RxCUI pair.
        Returns the interaction dict or None.
        """
        data = self._get(f"/interaction/list.json?rxcuis={rxcui_a}+{rxcui_b}")
        full_interaction_type_group = data.get("fullInteractionTypeGroup", [])

        for group in full_interaction_type_group:
            for itype in group.get("fullInteractionType", []):
                for pair in itype.get("interactionPair", []):
                    return {
                        "severity": pair.get("severity", "N/A"),
                        "description": pair.get("description", ""),
                        "source": group.get("sourceName", ""),
                    }
        return None

    def lookup_drug_name_from_rxcui(self, rxcui: str) -> str:
        """Get the display name for an RxCUI."""
        data = self._get(f"/rxcui/{rxcui}/properties.json")
        props = data.get("properties", {})
        return props.get("name", rxcui)
