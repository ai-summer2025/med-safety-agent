"""
FDA openFDA FAERS (Adverse Event Reporting System) API client.
Free public API — no key required.
Docs: https://open.fda.gov/apis/drug/event/
"""
import time
import logging
from typing import List, Dict, Any, Optional
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

FDA_BASE_URL = "https://api.fda.gov/drug/event.json"
DEFAULT_LIMIT = 100
REQUEST_DELAY = 0.5  # seconds between requests to be polite


class FDAClient:
    """Client for the openFDA Drug Adverse Event API (FAERS)."""

    def __init__(self, request_delay: float = REQUEST_DELAY, _mock_responses: Optional[Dict] = None):
        self.request_delay = request_delay
        self._mock_responses = _mock_responses  # For testing
        self._call_count = 0

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a GET request to the FDA API."""
        self._call_count += 1

        # Use mock responses if provided (for testing)
        if self._mock_responses is not None:
            key = params.get("search", "")
            if key in self._mock_responses:
                return self._mock_responses[key]
            # Return empty result for unmocked queries
            return {"results": [], "meta": {"results": {"total": 0}}}

        query_string = urllib.parse.urlencode(params)
        url = f"{FDA_BASE_URL}?{query_string}"
        logger.debug(f"FDA API GET: {url}")

        try:
            time.sleep(self.request_delay)
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # No results found — not an error
                return {"results": [], "meta": {"results": {"total": 0}}}
            logger.warning(f"FDA API HTTP error {e.code} for params={params}")
            return {"results": [], "meta": {"results": {"total": 0}}}
        except Exception as e:
            logger.warning(f"FDA API error: {e}")
            return {"results": [], "meta": {"results": {"total": 0}}}

    def get_adverse_events_for_drug(
        self, drug_name: str, limit: int = DEFAULT_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Query FAERS for adverse event reports for a specific drug.
        Returns raw report results.
        """
        # Search by drug brand name OR generic name
        search_query = f'patient.drug.medicinalproduct:"{drug_name}"'
        params = {
            "search": search_query,
            "limit": limit,
        }
        data = self._get(params)
        return data.get("results", [])

    def get_serious_event_counts(self, drug_name: str) -> Dict[str, int]:
        """
        Count serious vs non-serious adverse events for a drug.
        Returns {total, serious, non_serious}.
        """
        # Count total events
        total_params = {
            "search": f'patient.drug.medicinalproduct:"{drug_name}"',
            "count": "serious",
        }
        data = self._get(total_params)
        results = data.get("results", [])

        total = 0
        serious = 0
        for item in results:
            count = item.get("count", 0)
            val = item.get("term", 0)
            total += count
            if str(val) == "1":  # 1 = serious in FAERS
                serious += count

        return {"total": total, "serious": serious, "non_serious": total - serious}

    def get_top_reactions(self, drug_name: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most commonly reported reactions for a drug.
        Uses FAERS count endpoint.
        """
        params = {
            "search": f'patient.drug.medicinalproduct:"{drug_name}"',
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": top_n,
        }
        data = self._get(params)
        return data.get("results", [])

    def get_total_report_count(self, drug_name: str) -> int:
        """Get the total number of FAERS reports for this drug."""
        params = {
            "search": f'patient.drug.medicinalproduct:"{drug_name}"',
            "limit": 1,
        }
        data = self._get(params)
        meta = data.get("meta", {}).get("results", {})
        return meta.get("total", 0)
