"""
Comprehensive tests for the Drug Safety Agent.
Uses mock API responses — no real network calls needed.
"""
import pytest
from unittest.mock import patch, MagicMock

from models import (
    Medication, AdverseEvent, DrugInteraction, MedicationRiskProfile,
    PatientSafetyReport, RiskLevel
)
from fda_client import FDAClient
from rxnav_client import RxNavClient
from scorer import (
    score_medication_risk, score_overall_patient_risk,
    build_critical_alerts, build_recommendations
)
from agent import DrugSafetyAgent
from report import format_report, report_to_dict


# ============================================================
# FIXTURES — Mock API Responses
# ============================================================

@pytest.fixture
def mock_fda_sparse():
    """FDA client returning sparse results for brand name, richer for generic."""
    responses = {
        'patient.drug.medicinalproduct:"Coumadin"': {
            "results": [],
            "meta": {"results": {"total": 10}},
        },
        'patient.drug.medicinalproduct:"warfarin"': {
            "results": [{"term": "1", "count": 5000}, {"term": "2", "count": 3000}],
            "meta": {"results": {"total": 25000}},
        },
        'patient.drug.medicinalproduct:"aspirin"': {
            "results": [{"term": "1", "count": 2000}, {"term": "2", "count": 8000}],
            "meta": {"results": {"total": 30000}},
        },
    }
    return FDAClient(_mock_responses=responses)


@pytest.fixture
def mock_fda_normal():
    """Standard FDA mock with typical adverse event data."""
    responses = {
        'patient.drug.medicinalproduct:"warfarin"': {
            "results": [{"term": "1", "count": 50000}, {"term": "2", "count": 10000}],
            "meta": {"results": {"total": 150000}},
        },
        'patient.drug.medicinalproduct:"aspirin"': {
            "results": [{"term": "1", "count": 1000}, {"term": "2", "count": 19000}],
            "meta": {"results": {"total": 20000}},
        },
        'patient.drug.medicinalproduct:"metformin"': {
            "results": [{"term": "1", "count": 500}, {"term": "2", "count": 2000}],
            "meta": {"results": {"total": 5000}},
        },
        'patient.drug.medicinalproduct:"sertraline"': {
            "results": [{"term": "1", "count": 8000}, {"term": "2", "count": 2000}],
            "meta": {"results": {"total": 40000}},
        },
        'patient.drug.medicinalproduct:"tramadol"': {
            "results": [{"term": "1", "count": 15000}, {"term": "2", "count": 5000}],
            "meta": {"results": {"total": 55000}},
        },
    }
    return FDAClient(_mock_responses=responses)


@pytest.fixture
def mock_rxnav():
    """RxNav client with mock RxCUI lookups and interactions."""
    responses = {
        "/rxcui.json?name=warfarin&search=0": {
            "idGroup": {"rxnormId": ["202421"]}
        },
        "/rxcui.json?name=aspirin&search=0": {
            "idGroup": {"rxnormId": ["1191"]}
        },
        "/rxcui.json?name=metformin&search=0": {
            "idGroup": {"rxnormId": ["6809"]}
        },
        "/rxcui.json?name=sertraline&search=0": {
            "idGroup": {"rxnormId": ["36437"]}
        },
        "/rxcui.json?name=tramadol&search=0": {
            "idGroup": {"rxnormId": ["41493"]}
        },
        "/rxcui.json?name=lisinopril&search=0": {
            "idGroup": {"rxnormId": ["29046"]}
        },
        # Drug interactions
        "/interaction/list.json?rxcuis=202421+1191": {
            "fullInteractionTypeGroup": [{
                "sourceName": "DrugBank",
                "fullInteractionType": [{
                    "interactionPair": [{
                        "severity": "serious",
                        "description": "Warfarin and aspirin both inhibit platelet aggregation and may increase bleeding risk.",
                    }]
                }]
            }]
        },
        "/interaction/list.json?rxcuis=36437+41493": {
            "fullInteractionTypeGroup": [{
                "sourceName": "DrugBank",
                "fullInteractionType": [{
                    "interactionPair": [{
                        "severity": "contraindicated",
                        "description": "Concurrent use of sertraline and tramadol may increase risk of serotonin syndrome.",
                    }]
                }]
            }]
        },
        "/interaction/list.json?rxcuis=202421+6809": {},
        "/interaction/list.json?rxcuis=1191+6809": {},
    }
    return RxNavClient(_mock_responses=responses)


# ============================================================
# MODELS — Unit Tests
# ============================================================

class TestMedication:
    def test_medication_creation_minimal(self):
        med = Medication(name="warfarin")
        assert med.name == "warfarin"
        assert med.rxcui is None
        assert med.dose is None

    def test_medication_creation_full(self):
        med = Medication(
            name="warfarin", rxcui="202421",
            generic_name="warfarin", dose="5mg", frequency="daily"
        )
        assert med.name == "warfarin"
        assert med.rxcui == "202421"
        assert med.dose == "5mg"
        assert med.frequency == "daily"

    def test_medication_repr(self):
        med = Medication(name="aspirin", dose="81mg")
        assert "aspirin" in repr(med)
        assert "81mg" in repr(med)


class TestDrugInteraction:
    def test_interaction_serious(self):
        ix = DrugInteraction(
            drug_a="warfarin", drug_b="aspirin",
            severity="serious", description="Increased bleeding risk"
        )
        assert ix.is_serious is True

    def test_interaction_contraindicated(self):
        ix = DrugInteraction(
            drug_a="sertraline", drug_b="tramadol",
            severity="contraindicated", description="Serotonin syndrome risk"
        )
        assert ix.is_serious is True

    def test_interaction_moderate_not_serious(self):
        ix = DrugInteraction(
            drug_a="metformin", drug_b="lisinopril",
            severity="moderate", description="Minor interaction"
        )
        assert ix.is_serious is False

    def test_interaction_na_not_serious(self):
        ix = DrugInteraction(
            drug_a="A", drug_b="B", severity="N/A", description=""
        )
        assert ix.is_serious is False

    def test_interaction_repr(self):
        ix = DrugInteraction(
            drug_a="warfarin", drug_b="aspirin",
            severity="serious", description="test"
        )
        assert "warfarin" in repr(ix)
        assert "aspirin" in repr(ix)


class TestRiskLevel:
    def test_risk_level_values(self):
        assert RiskLevel.LOW.value == "LOW"
        assert RiskLevel.MEDIUM.value == "MEDIUM"
        assert RiskLevel.HIGH.value == "HIGH"
        assert RiskLevel.CRITICAL.value == "CRITICAL"

    def test_risk_level_ordering(self):
        levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert levels[0] != levels[1]
        assert levels[3] != levels[0]


class TestAdverseEvent:
    def test_adverse_event_serious(self):
        ae = AdverseEvent(drug_name="warfarin", reaction="death", serious=True)
        assert ae.serious is True
        assert ae.drug_name == "warfarin"

    def test_adverse_event_non_serious(self):
        ae = AdverseEvent(drug_name="aspirin", reaction="nausea", serious=False)
        assert ae.serious is False

    def test_adverse_event_repr(self):
        ae = AdverseEvent(drug_name="warfarin", reaction="hemorrhage", serious=True)
        assert "warfarin" in repr(ae)


class TestPatientSafetyReport:
    def test_report_defaults(self):
        meds = [Medication(name="aspirin")]
        report = PatientSafetyReport(patient_id="PT001", medications=meds)
        assert report.overall_risk == RiskLevel.LOW
        assert report.critical_alerts == []
        assert report.recommendations == []
        assert report.agent_iterations == 0

    def test_report_repr(self):
        meds = [Medication(name="aspirin")]
        report = PatientSafetyReport(
            patient_id="PT001", medications=meds, overall_risk=RiskLevel.HIGH
        )
        assert "PT001" in repr(report)
        assert "HIGH" in repr(report)


# ============================================================
# FDA CLIENT — Unit Tests
# ============================================================

class TestFDAClient:
    def test_client_returns_empty_on_unknown(self):
        client = FDAClient(_mock_responses={})
        result = client.get_adverse_events_for_drug("unknown_drug_xyz")
        assert result == []

    def test_get_total_report_count_zero(self):
        client = FDAClient(_mock_responses={})
        count = client.get_total_report_count("unknown")
        assert count == 0

    def test_get_serious_event_counts_empty(self):
        client = FDAClient(_mock_responses={})
        counts = client.get_serious_event_counts("unknown")
        assert counts["total"] == 0
        assert counts["serious"] == 0
        assert counts["non_serious"] == 0

    def test_get_top_reactions_empty(self):
        client = FDAClient(_mock_responses={})
        reactions = client.get_top_reactions("unknown", top_n=5)
        assert reactions == []

    def test_call_count_tracks_requests(self):
        client = FDAClient(_mock_responses={})
        client.get_top_reactions("X")
        client.get_total_report_count("Y")
        assert client._call_count == 2

    def test_get_serious_event_counts_with_mock(self):
        mock = {
            'patient.drug.medicinalproduct:"warfarin"': {
                "results": [{"term": 1, "count": 50000}, {"term": 2, "count": 10000}],
                "meta": {"results": {"total": 60000}},
            }
        }
        client = FDAClient(_mock_responses=mock)
        counts = client.get_serious_event_counts("warfarin")
        assert counts["serious"] == 50000
        assert counts["non_serious"] == 10000


# ============================================================
# RXNAV CLIENT — Unit Tests
# ============================================================

class TestRxNavClient:
    def test_find_rxcui_found(self, mock_rxnav):
        rxcui = mock_rxnav.find_rxcui("warfarin")
        assert rxcui == "202421"

    def test_find_rxcui_aspirin(self, mock_rxnav):
        rxcui = mock_rxnav.find_rxcui("aspirin")
        assert rxcui == "1191"

    def test_find_rxcui_not_found(self):
        client = RxNavClient(_mock_responses={})
        rxcui = client.find_rxcui("nonexistent_drug_xyz")
        assert rxcui is None

    def test_get_interaction_between_pair_found(self, mock_rxnav):
        result = mock_rxnav.get_interaction_between_pair("202421", "1191")
        assert result is not None
        assert result["severity"] == "serious"
        assert "bleeding" in result["description"].lower()

    def test_get_interaction_between_pair_none(self, mock_rxnav):
        result = mock_rxnav.get_interaction_between_pair("202421", "6809")
        assert result is None

    def test_get_interaction_contraindicated(self, mock_rxnav):
        result = mock_rxnav.get_interaction_between_pair("36437", "41493")
        assert result is not None
        assert result["severity"] == "contraindicated"

    def test_call_count_tracks(self):
        # find_rxcui makes 2 HTTP calls per invocation:
        # (1) exact match /rxcui.json, (2) approximate /approximateTerm.json
        # So two find_rxcui calls = 4 total _call_count increments.
        client = RxNavClient(_mock_responses={})
        client.find_rxcui("X")
        client.find_rxcui("Y")
        assert client._call_count == 4


# ============================================================
# SCORER — Unit Tests
# ============================================================

class TestScoreMedicationRisk:
    def test_low_risk_few_events(self):
        med = Medication(name="aspirin")
        profile = score_medication_risk(
            medication=med, serious_count=100, total_count=1000, top_reactions=["nausea"]
        )
        assert profile.risk_level == RiskLevel.LOW

    def test_medium_risk(self):
        med = Medication(name="aspirin")
        profile = score_medication_risk(
            medication=med, serious_count=2500, total_count=10000,
            top_reactions=["nausea", "vomiting"]
        )
        assert profile.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_high_risk_many_serious_events(self):
        med = Medication(name="warfarin")
        profile = score_medication_risk(
            medication=med, serious_count=15000, total_count=20000,
            top_reactions=["hemorrhage", "dizziness"]
        )
        assert profile.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_critical_risk_high_ratio_and_count(self):
        med = Medication(name="test_drug")
        profile = score_medication_risk(
            medication=med, serious_count=55000, total_count=60000,
            top_reactions=["death", "cardiac arrest"]
        )
        assert profile.risk_level == RiskLevel.CRITICAL

    def test_high_risk_from_dangerous_reactions(self):
        med = Medication(name="test_drug")
        profile = score_medication_risk(
            medication=med, serious_count=500, total_count=10000,
            top_reactions=["death", "anaphylaxis"]
        )
        # Should be at least HIGH due to dangerous reaction keywords
        assert profile.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_top_reactions_stored(self):
        med = Medication(name="aspirin")
        reactions = ["nausea", "headache", "dizziness"]
        profile = score_medication_risk(
            medication=med, serious_count=100, total_count=500, top_reactions=reactions
        )
        assert profile.top_reactions == reactions

    def test_profile_medication_preserved(self):
        med = Medication(name="warfarin", dose="5mg")
        profile = score_medication_risk(
            medication=med, serious_count=0, total_count=0, top_reactions=[]
        )
        assert profile.medication.name == "warfarin"
        assert profile.medication.dose == "5mg"


class TestScoreOverallPatientRisk:
    def test_all_low_risk_meds_no_interactions(self):
        meds = [Medication(name="aspirin"), Medication(name="metformin")]
        profiles = [
            MedicationRiskProfile(medication=meds[0], risk_level=RiskLevel.LOW),
            MedicationRiskProfile(medication=meds[1], risk_level=RiskLevel.LOW),
        ]
        risk = score_overall_patient_risk(profiles, [])
        assert risk == RiskLevel.LOW

    def test_one_high_risk_med_elevates_overall(self):
        meds = [Medication(name="warfarin"), Medication(name="aspirin")]
        profiles = [
            MedicationRiskProfile(medication=meds[0], risk_level=RiskLevel.HIGH),
            MedicationRiskProfile(medication=meds[1], risk_level=RiskLevel.LOW),
        ]
        risk = score_overall_patient_risk(profiles, [])
        assert risk == RiskLevel.HIGH

    def test_serious_interaction_elevates_risk(self):
        meds = [Medication(name="aspirin")]
        profiles = [
            MedicationRiskProfile(medication=meds[0], risk_level=RiskLevel.LOW),
        ]
        interactions = [
            DrugInteraction(
                drug_a="A", drug_b="B", severity="serious",
                description="Bleeding risk"
            ),
            DrugInteraction(
                drug_a="A", drug_b="C", severity="serious",
                description="Another risk"
            ),
        ]
        risk = score_overall_patient_risk(profiles, interactions)
        assert risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_contraindicated_interaction_elevates_to_critical(self):
        meds = [Medication(name="A")]
        profiles = [
            MedicationRiskProfile(medication=meds[0], risk_level=RiskLevel.MEDIUM),
        ]
        interactions = [
            DrugInteraction(
                drug_a="X", drug_b="Y", severity="contraindicated",
                description="Dangerous"
            ),
            DrugInteraction(
                drug_a="X", drug_b="Z", severity="contraindicated",
                description="Also dangerous"
            ),
            DrugInteraction(
                drug_a="X", drug_b="W", severity="serious",
                description="Serious"
            ),
        ]
        risk = score_overall_patient_risk(profiles, interactions)
        assert risk == RiskLevel.CRITICAL

    def test_empty_medications(self):
        risk = score_overall_patient_risk([], [])
        assert risk == RiskLevel.LOW


class TestBuildCriticalAlerts:
    def test_high_risk_med_generates_alert(self):
        med = Medication(name="warfarin")
        profiles = [
            MedicationRiskProfile(
                medication=med, risk_level=RiskLevel.HIGH,
                serious_event_count=20000, total_event_count=50000
            )
        ]
        alerts = build_critical_alerts(profiles, [])
        assert len(alerts) > 0
        assert "warfarin" in alerts[0]

    def test_serious_interaction_generates_alert(self):
        ix = DrugInteraction(
            drug_a="warfarin", drug_b="aspirin",
            severity="serious", description="Bleeding risk"
        )
        alerts = build_critical_alerts([], [ix])
        assert len(alerts) > 0
        assert "INTERACTION" in alerts[0]

    def test_low_risk_no_alerts(self):
        med = Medication(name="aspirin")
        profiles = [
            MedicationRiskProfile(
                medication=med, risk_level=RiskLevel.LOW,
                serious_event_count=10, total_event_count=100
            )
        ]
        alerts = build_critical_alerts(profiles, [])
        assert alerts == []


class TestBuildRecommendations:
    def test_critical_risk_first_recommendation(self):
        recs = build_recommendations([], [], RiskLevel.CRITICAL)
        assert len(recs) > 0
        assert "CRITICAL" in recs[0]

    def test_high_risk_recommendation(self):
        recs = build_recommendations([], [], RiskLevel.HIGH)
        assert len(recs) > 0
        assert "HIGH" in recs[0]

    def test_low_risk_positive_recommendation(self):
        recs = build_recommendations([], [], RiskLevel.LOW)
        assert len(recs) > 0
        assert "LOW" in recs[0]

    def test_contraindicated_generates_extra_rec(self):
        ix = DrugInteraction(
            drug_a="A", drug_b="B", severity="contraindicated",
            description="Do not use together"
        )
        recs = build_recommendations([], [ix], RiskLevel.HIGH)
        assert any("CONTRAINDICATED" in r for r in recs)

    def test_high_risk_meds_generate_review_rec(self):
        med = Medication(name="warfarin")
        profiles = [
            MedicationRiskProfile(medication=med, risk_level=RiskLevel.HIGH)
        ]
        recs = build_recommendations(profiles, [], RiskLevel.HIGH)
        assert any("warfarin" in r for r in recs)


# ============================================================
# AGENT — Integration Tests (with mocks)
# ============================================================

class TestDrugSafetyAgent:
    def test_resolve_rxcuis(self, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=FDAClient(_mock_responses={}), rxnav_client=mock_rxnav)
        meds = [Medication(name="warfarin"), Medication(name="aspirin")]
        result = agent.resolve_rxcuis(meds)
        assert result[0].rxcui == "202421"
        assert result[1].rxcui == "1191"

    def test_resolve_rxcuis_unknown_drug(self, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=FDAClient(_mock_responses={}), rxnav_client=mock_rxnav)
        meds = [Medication(name="unknown_fictional_drug_xyz")]
        result = agent.resolve_rxcuis(meds)
        assert result[0].rxcui is None

    def test_check_interactions_finds_serious(self, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=FDAClient(_mock_responses={}), rxnav_client=mock_rxnav)
        meds = [
            Medication(name="warfarin", rxcui="202421"),
            Medication(name="aspirin", rxcui="1191"),
        ]
        interactions = agent.check_interactions(meds)
        assert len(interactions) >= 1
        assert interactions[0].severity == "serious"

    def test_check_interactions_contraindicated(self, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=FDAClient(_mock_responses={}), rxnav_client=mock_rxnav)
        meds = [
            Medication(name="sertraline", rxcui="36437"),
            Medication(name="tramadol", rxcui="41493"),
        ]
        interactions = agent.check_interactions(meds)
        assert len(interactions) >= 1
        assert interactions[0].severity == "contraindicated"

    def test_check_interactions_no_rxcui_skipped(self, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=FDAClient(_mock_responses={}), rxnav_client=mock_rxnav)
        meds = [
            Medication(name="drug_a"),  # No rxcui
            Medication(name="drug_b"),  # No rxcui
        ]
        interactions = agent.check_interactions(meds)
        assert interactions == []

    def test_full_evaluate_returns_report(self, mock_fda_normal, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=mock_fda_normal, rxnav_client=mock_rxnav)
        meds = [
            Medication(name="warfarin", generic_name="warfarin"),
            Medication(name="aspirin", generic_name="aspirin"),
            Medication(name="metformin", generic_name="metformin"),
        ]
        report = agent.evaluate(patient_id="TEST-001", medications=meds)

        assert isinstance(report, PatientSafetyReport)
        assert report.patient_id == "TEST-001"
        assert len(report.medication_profiles) == 3
        assert report.overall_risk in list(RiskLevel)
        assert report.agent_iterations >= 1

    def test_evaluate_high_risk_scenario(self, mock_rxnav):
        """Sertraline + tramadol should yield at least HIGH risk due to contraindication."""
        fda_mock = {
            'patient.drug.medicinalproduct:"sertraline"': {
                "results": [{"term": 1, "count": 8000}],
                "meta": {"results": {"total": 40000}},
            },
            'patient.drug.medicinalproduct:"tramadol"': {
                "results": [{"term": 1, "count": 15000}],
                "meta": {"results": {"total": 55000}},
            },
        }
        fda_client = FDAClient(_mock_responses=fda_mock)
        agent = DrugSafetyAgent(fda_client=fda_client, rxnav_client=mock_rxnav)
        meds = [
            Medication(name="sertraline", generic_name="sertraline"),
            Medication(name="tramadol", generic_name="tramadol"),
        ]
        report = agent.evaluate(patient_id="TEST-002", medications=meds)
        assert report.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_evaluate_single_medication(self, mock_rxnav):
        fda_mock = {
            'patient.drug.medicinalproduct:"metformin"': {
                "results": [{"term": 2, "count": 500}],
                "meta": {"results": {"total": 1000}},
            }
        }
        fda_client = FDAClient(_mock_responses=fda_mock)
        agent = DrugSafetyAgent(fda_client=fda_client, rxnav_client=mock_rxnav)
        meds = [Medication(name="metformin", generic_name="metformin")]
        report = agent.evaluate(patient_id="SINGLE-001", medications=meds)
        assert len(report.medication_profiles) == 1
        assert len(report.interactions) == 0  # Single drug, no pairs

    def test_evaluate_returns_recommendations(self, mock_fda_normal, mock_rxnav):
        agent = DrugSafetyAgent(fda_client=mock_fda_normal, rxnav_client=mock_rxnav)
        meds = [
            Medication(name="warfarin", generic_name="warfarin"),
            Medication(name="aspirin", generic_name="aspirin"),
        ]
        report = agent.evaluate(patient_id="REC-001", medications=meds)
        assert len(report.recommendations) > 0


# ============================================================
# REPORT — Unit Tests
# ============================================================

class TestFormatReport:
    def _make_report(self, risk=RiskLevel.LOW):
        meds = [Medication(name="aspirin"), Medication(name="metformin")]
        report = PatientSafetyReport(
            patient_id="RPT-001",
            medications=meds,
            overall_risk=risk,
            medication_profiles=[
                MedicationRiskProfile(
                    medication=meds[0],
                    risk_level=RiskLevel.LOW,
                    serious_event_count=100,
                    total_event_count=1000,
                    top_reactions=["nausea", "headache"],
                ),
                MedicationRiskProfile(
                    medication=meds[1],
                    risk_level=RiskLevel.LOW,
                    serious_event_count=50,
                    total_event_count=500,
                ),
            ],
            interactions=[],
            critical_alerts=[],
            recommendations=["Routine follow-up."],
            agent_iterations=1,
            total_api_calls=10,
        )
        return report

    def test_format_contains_patient_id(self):
        report = self._make_report()
        text = format_report(report)
        assert "RPT-001" in text

    def test_format_contains_risk_level(self):
        report = self._make_report(RiskLevel.HIGH)
        text = format_report(report)
        assert "HIGH" in text

    def test_format_contains_medication_names(self):
        report = self._make_report()
        text = format_report(report)
        assert "aspirin" in text
        assert "metformin" in text

    def test_format_no_interactions_message(self):
        report = self._make_report()
        text = format_report(report)
        assert "No significant drug interactions detected" in text

    def test_format_contains_recommendations(self):
        report = self._make_report()
        text = format_report(report)
        assert "Routine follow-up" in text

    def test_format_contains_api_calls(self):
        report = self._make_report()
        text = format_report(report)
        assert "10" in text

    def test_format_with_interactions(self):
        report = self._make_report(RiskLevel.HIGH)
        report.interactions = [
            DrugInteraction(
                drug_a="warfarin", drug_b="aspirin",
                severity="serious", description="Bleeding risk"
            )
        ]
        text = format_report(report)
        assert "warfarin" in text
        assert "SERIOUS" in text

    def test_report_to_dict_structure(self):
        report = self._make_report()
        d = report_to_dict(report)
        assert "patient_id" in d
        assert "overall_risk" in d
        assert "medications" in d
        assert "medication_profiles" in d
        assert "interactions" in d
        assert "critical_alerts" in d
        assert "recommendations" in d
        assert isinstance(d["medications"], list)

    def test_report_to_dict_serializable(self):
        import json
        report = self._make_report()
        d = report_to_dict(report)
        # Should not raise
        json_str = json.dumps(d)
        assert "RPT-001" in json_str

    def test_report_to_dict_risk_value(self):
        report = self._make_report(RiskLevel.CRITICAL)
        d = report_to_dict(report)
        assert d["overall_risk"] == "CRITICAL"
