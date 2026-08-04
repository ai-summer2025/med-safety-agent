"""
Drug Safety Agent — Main Agentic Loop.

A multi-step autonomous agent that:
  1. Parses a patient's medication list
  2. Resolves drug names to RxCUI identifiers (RxNav)
  3. Queries FDA FAERS for adverse event data per medication
  4. Checks drug-drug interactions for all pairs (RxNav)
  5. Scores risk with severity tiers
  6. Adaptively re-queries with generic names if brand-name results are sparse
  7. Generates a structured patient safety report

Free public APIs used:
  - openFDA Drug Adverse Event API: https://api.fda.gov/drug/event.json
  - NIH RxNav Drug Interaction API: https://rxnav.nlm.nih.gov/REST/
"""
import logging
from itertools import combinations
from typing import List, Optional, Dict, Any

from models import (
    Medication, DrugInteraction, PatientSafetyReport, RiskLevel
)
from fda_client import FDAClient
from rxnav_client import RxNavClient
from scorer import (
    score_medication_risk,
    score_overall_patient_risk,
    build_critical_alerts,
    build_recommendations,
)

logger = logging.getLogger(__name__)

# If total report count for a drug is below this threshold, trigger re-query
SPARSE_RESULT_THRESHOLD = 50
MAX_AGENT_ITERATIONS = 3


class DrugSafetyAgent:
    """
    Agentic loop that autonomously evaluates a patient's medication safety.
    """

    def __init__(
        self,
        fda_client: Optional[FDAClient] = None,
        rxnav_client: Optional[RxNavClient] = None,
    ):
        self.fda = fda_client or FDAClient()
        self.rxnav = rxnav_client or RxNavClient()
        self._iterations = 0
        self._total_api_calls = 0

    # ------------------------------------------------------------------
    # STEP 1: Resolve RxCUIs for each medication
    # ------------------------------------------------------------------
    def resolve_rxcuis(self, medications: List[Medication]) -> List[Medication]:
        """
        Resolve each medication to an RxCUI using RxNav.
        Mutates medications in-place; returns same list.
        """
        logger.info(f"[Agent] STEP 1 — Resolving RxCUIs for {len(medications)} medications")
        for med in medications:
            if not med.rxcui:
                rxcui = self.rxnav.find_rxcui(med.name)
                if rxcui:
                    med.rxcui = rxcui
                    logger.debug(f"  Resolved {med.name!r} → RxCUI {rxcui}")
                else:
                    logger.debug(f"  No RxCUI found for {med.name!r}")
        self._total_api_calls += len(medications)
        return medications

    # ------------------------------------------------------------------
    # STEP 2: Query FDA FAERS per medication, with adaptive re-query
    # ------------------------------------------------------------------
    def query_fda_adverse_events(self, medications: List[Medication]) -> Dict[str, Any]:
        """
        For each medication:
          - Get total FAERS report count
          - Get serious event counts
          - Get top MedDRA reactions
          - If results sparse (< SPARSE_RESULT_THRESHOLD), try generic name
        Returns dict keyed by medication name with FDA data.
        """
        logger.info(f"[Agent] STEP 2 — Querying FDA FAERS for {len(medications)} medications")
        fda_data: Dict[str, Any] = {}

        for med in medications:
            query_name = med.name
            total = self.fda.get_total_report_count(query_name)
            self._total_api_calls += 1

            # Adaptive re-query: if sparse, try generic name
            if total < SPARSE_RESULT_THRESHOLD and med.generic_name:
                logger.info(
                    f"  Sparse results for {query_name!r} ({total} reports). "
                    f"Re-querying with generic name {med.generic_name!r}"
                )
                generic_total = self.fda.get_total_report_count(med.generic_name)
                self._total_api_calls += 1
                if generic_total > total:
                    query_name = med.generic_name
                    total = generic_total

            counts = self.fda.get_serious_event_counts(query_name)
            reactions_raw = self.fda.get_top_reactions(query_name, top_n=15)
            self._total_api_calls += 2

            top_reactions = [r.get("term", "") for r in reactions_raw if r.get("term")]

            fda_data[med.name] = {
                "query_name": query_name,
                "total_reports": total,
                "serious_count": counts.get("serious", 0),
                "non_serious_count": counts.get("non_serious", 0),
                "top_reactions": top_reactions,
            }

            logger.info(
                f"  {med.name!r}: {total:,} total reports, "
                f"{counts.get('serious', 0):,} serious, "
                f"top reactions: {top_reactions[:3]}"
            )

        return fda_data

    # ------------------------------------------------------------------
    # STEP 3: Check drug-drug interactions for all pairs
    # ------------------------------------------------------------------
    def check_interactions(self, medications: List[Medication]) -> List[DrugInteraction]:
        """
        Check all pairwise drug-drug interactions using RxNav.
        Uses RxCUI-based lookup for accuracy.
        """
        logger.info(f"[Agent] STEP 3 — Checking drug-drug interactions for all pairs")
        interactions = []

        meds_with_rxcui = [m for m in medications if m.rxcui]
        pairs = list(combinations(meds_with_rxcui, 2))
        logger.info(f"  Checking {len(pairs)} medication pairs")

        for med_a, med_b in pairs:
            result = self.rxnav.get_interaction_between_pair(med_a.rxcui, med_b.rxcui)
            self._total_api_calls += 1

            if result:
                interaction = DrugInteraction(
                    drug_a=med_a.name,
                    drug_b=med_b.name,
                    severity=result.get("severity", "N/A"),
                    description=result.get("description", "No description available"),
                    rxcui_a=med_a.rxcui,
                    rxcui_b=med_b.rxcui,
                )
                interactions.append(interaction)
                logger.info(
                    f"  INTERACTION: {med_a.name} ↔ {med_b.name} "
                    f"[{interaction.severity}]"
                )
            else:
                logger.debug(f"  No interaction found: {med_a.name} ↔ {med_b.name}")

        return interactions

    # ------------------------------------------------------------------
    # STEP 4: Score risks
    # ------------------------------------------------------------------
    def score_risks(self, medications: List[Medication], fda_data: Dict[str, Any]):
        """Build MedicationRiskProfile for each medication."""
        logger.info(f"[Agent] STEP 4 — Scoring medication risks")
        profiles = []
        for med in medications:
            data = fda_data.get(med.name, {})
            profile = score_medication_risk(
                medication=med,
                serious_count=data.get("serious_count", 0),
                total_count=data.get("total_reports", 0),
                top_reactions=data.get("top_reactions", []),
            )
            profiles.append(profile)
            logger.info(f"  {med.name!r}: risk={profile.risk_level.value}")
        return profiles

    # ------------------------------------------------------------------
    # MAIN AGENTIC LOOP
    # ------------------------------------------------------------------
    def evaluate(self, patient_id: str, medications: List[Medication]) -> PatientSafetyReport:
        """
        Run the full agentic evaluation loop for a patient's medication list.

        The loop iterates up to MAX_AGENT_ITERATIONS times. In each iteration:
          - Resolve RxCUIs
          - Query FDA FAERS
          - Check interactions
          - Score risks
          - If overall risk is CRITICAL on first pass, perform a second pass
            with expanded reaction list to confirm (agentic validation)
        """
        logger.info(f"[Agent] === Starting Drug Safety Evaluation for patient {patient_id!r} ===")
        logger.info(f"[Agent] Medications: {[m.name for m in medications]}")

        report = PatientSafetyReport(
            patient_id=patient_id,
            medications=medications,
        )

        for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
            self._iterations = iteration
            logger.info(f"[Agent] --- Iteration {iteration} ---")

            # Step 1: Resolve identifiers
            medications = self.resolve_rxcuis(medications)

            # Step 2: FDA adverse event data
            fda_data = self.query_fda_adverse_events(medications)

            # Step 3: Drug-drug interactions
            interactions = self.check_interactions(medications)

            # Step 4: Score individual medications
            medication_profiles = self.score_risks(medications, fda_data)

            # Step 5: Overall patient risk
            overall_risk = score_overall_patient_risk(medication_profiles, interactions)
            logger.info(f"[Agent] Overall risk after iteration {iteration}: {overall_risk.value}")

            # Agentic decision: if CRITICAL, do one more validation pass
            # with a broader generic-name query to confirm
            if overall_risk == RiskLevel.CRITICAL and iteration < MAX_AGENT_ITERATIONS:
                logger.info(
                    "[Agent] CRITICAL risk detected. Performing additional validation pass "
                    "with broader generic-name queries..."
                )
                # Force generic name re-query by temporarily clearing totals
                for med in medications:
                    if not med.generic_name and med.name.lower() != med.name:
                        # Guess generic by lowercasing brand name (heuristic)
                        med.generic_name = med.name.lower()
                continue  # next iteration

            # Converged — build final report
            report.medication_profiles = medication_profiles
            report.interactions = interactions
            report.overall_risk = overall_risk
            report.critical_alerts = build_critical_alerts(medication_profiles, interactions)
            report.recommendations = build_recommendations(
                medication_profiles, interactions, overall_risk
            )
            report.agent_iterations = self._iterations
            report.total_api_calls = self._total_api_calls + self.fda._call_count + self.rxnav._call_count
            break

        logger.info(f"[Agent] === Evaluation complete. Risk: {report.overall_risk.value} ===")
        return report
