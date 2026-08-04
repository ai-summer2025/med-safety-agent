"""
Risk scoring engine for the Drug Safety Agent.
Translates raw FDA/RxNav data into tiered risk levels.
"""
from typing import List
from models import (
    RiskLevel, Medication, MedicationRiskProfile,
    DrugInteraction, AdverseEvent, PatientSafetyReport
)


# Thresholds for individual drug adverse event risk scoring
SERIOUS_EVENT_THRESHOLDS = {
    RiskLevel.CRITICAL: 50_000,
    RiskLevel.HIGH: 10_000,
    RiskLevel.MEDIUM: 2_000,
    RiskLevel.LOW: 0,
}

# Thresholds based on proportion of serious events
SERIOUS_RATIO_THRESHOLDS = {
    RiskLevel.CRITICAL: 0.80,
    RiskLevel.HIGH: 0.60,
    RiskLevel.MEDIUM: 0.30,
    RiskLevel.LOW: 0.0,
}

# Interaction severity weights
INTERACTION_SEVERITY_WEIGHTS = {
    "contraindicated": 4,
    "serious": 3,
    "moderate": 2,
    "minor": 1,
    "N/A": 0,
    "n/a": 0,
}

# High-risk reaction keywords (MedDRA terms that are especially dangerous)
HIGH_RISK_REACTIONS = {
    "death", "cardiac arrest", "anaphylaxis", "anaphylactic shock",
    "respiratory failure", "respiratory arrest", "hepatic failure",
    "liver failure", "renal failure", "kidney failure",
    "Stevens-Johnson syndrome", "toxic epidermal necrolysis",
    "aplastic anaemia", "agranulocytosis", "pulmonary embolism",
    "cerebrovascular accident", "myocardial infarction",
    "sudden death", "cardiac failure", "septic shock",
}


def score_medication_risk(
    medication: Medication,
    serious_count: int,
    total_count: int,
    top_reactions: List[str],
) -> MedicationRiskProfile:
    """Score risk for a single medication based on FAERS data."""
    # Determine risk from absolute count of serious events
    risk_from_count = RiskLevel.LOW
    for level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM]:
        if serious_count >= SERIOUS_EVENT_THRESHOLDS[level]:
            risk_from_count = level
            break

    # Determine risk from ratio of serious events
    risk_from_ratio = RiskLevel.LOW
    if total_count > 0:
        ratio = serious_count / total_count
        for level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM]:
            if ratio >= SERIOUS_RATIO_THRESHOLDS[level]:
                risk_from_ratio = level
                break

    # Determine risk from reaction types
    risk_from_reactions = RiskLevel.LOW
    reactions_lower = {str(r).lower() for r in top_reactions}
    for keyword in HIGH_RISK_REACTIONS:
        if keyword.lower() in reactions_lower:
            risk_from_reactions = RiskLevel.HIGH
            break

    # Overall risk is the maximum of all three factors
    levels_ordered = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    all_levels = [risk_from_count, risk_from_ratio, risk_from_reactions]
    overall = max(all_levels, key=lambda l: levels_ordered.index(l))

    # Build adverse event list from top reactions
    adverse_events = [
        AdverseEvent(
            drug_name=medication.name,
            reaction=str(r),
            serious=str(r).lower() in {k.lower() for k in HIGH_RISK_REACTIONS},
        )
        for r in top_reactions
    ]

    return MedicationRiskProfile(
        medication=medication,
        adverse_events=adverse_events,
        serious_event_count=serious_count,
        total_event_count=total_count,
        risk_level=overall,
        top_reactions=top_reactions,
    )


def score_overall_patient_risk(
    medication_profiles: List[MedicationRiskProfile],
    interactions: List[DrugInteraction],
) -> RiskLevel:
    """
    Compute the overall patient risk level by combining:
    - Highest individual medication risk
    - Interaction severity weights
    """
    levels_ordered = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    # Start with highest individual medication risk
    if medication_profiles:
        highest_med_risk = max(
            medication_profiles,
            key=lambda p: levels_ordered.index(p.risk_level)
        ).risk_level
    else:
        highest_med_risk = RiskLevel.LOW

    # Score interactions
    interaction_score = sum(
        INTERACTION_SEVERITY_WEIGHTS.get(i.severity.lower(), 0)
        for i in interactions
    )

    # Bump risk level based on interaction score
    if interaction_score >= 8:
        interaction_risk = RiskLevel.CRITICAL
    elif interaction_score >= 4:
        interaction_risk = RiskLevel.HIGH
    elif interaction_score >= 2:
        interaction_risk = RiskLevel.MEDIUM
    else:
        interaction_risk = RiskLevel.LOW

    # Return max of medication risk and interaction risk
    return max(
        [highest_med_risk, interaction_risk],
        key=lambda l: levels_ordered.index(l)
    )


def build_critical_alerts(
    medication_profiles: List[MedicationRiskProfile],
    interactions: List[DrugInteraction],
) -> List[str]:
    """Build a list of human-readable critical alert strings."""
    alerts = []

    for profile in medication_profiles:
        if profile.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            alerts.append(
                f"⚠️  {profile.medication.name}: {profile.serious_event_count:,} serious adverse "
                f"events in FDA FAERS (risk: {profile.risk_level.value})"
            )

    for interaction in interactions:
        if interaction.is_serious:
            alerts.append(
                f"🚨 INTERACTION [{interaction.severity.upper()}]: "
                f"{interaction.drug_a} ↔ {interaction.drug_b} — {interaction.description[:100]}"
            )

    return alerts


def build_recommendations(
    medication_profiles: List[MedicationRiskProfile],
    interactions: List[DrugInteraction],
    overall_risk: RiskLevel,
) -> List[str]:
    """Build clinical recommendations based on risk findings."""
    recs = []

    if overall_risk == RiskLevel.CRITICAL:
        recs.append(
            "🔴 CRITICAL RISK: Immediate pharmacist and physician review required before dispensing."
        )
    elif overall_risk == RiskLevel.HIGH:
        recs.append(
            "🟠 HIGH RISK: Pharmacist consultation recommended. Monitor patient closely."
        )
    elif overall_risk == RiskLevel.MEDIUM:
        recs.append(
            "🟡 MEDIUM RISK: Review medication list with prescriber. Educate patient on side effects."
        )
    else:
        recs.append(
            "🟢 LOW RISK: Continue monitoring. Routine follow-up as scheduled."
        )

    # Interaction-specific recommendations
    contraindicated = [i for i in interactions if i.severity.lower() == "contraindicated"]
    if contraindicated:
        for ix in contraindicated:
            recs.append(
                f"❌ CONTRAINDICATED combination: {ix.drug_a} + {ix.drug_b} — "
                "Discuss alternative therapy with prescriber."
            )

    serious_interactions = [i for i in interactions if i.severity.lower() == "serious"]
    if serious_interactions:
        recs.append(
            f"⚡ {len(serious_interactions)} serious drug interaction(s) detected — "
            "Enhanced monitoring or dose adjustment may be required."
        )

    # High adverse event burden
    high_risk_meds = [
        p for p in medication_profiles
        if p.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    ]
    if high_risk_meds:
        names = ", ".join(p.medication.name for p in high_risk_meds)
        recs.append(
            f"📋 Review high-burden medications ({names}) for dose optimization or alternatives."
        )

    return recs
