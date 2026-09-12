from app.schemas.documents import PolicyValidationStatus, TriageQueue
from app.services.policy_validation import apply_policy_validation
from app.services.triage import build_triage_result
from app.services.validator import IncomingFile, validate_claim
from app.services.workflow import run_claim_workflow


def _documents(*, accident_date: str, policy_period: str) -> list[IncomingFile]:
    return [
        IncomingFile("claim.txt", f"Claim Form claim number CLM-2024-000123 date of loss {accident_date} vehicle HR26 AB 1234".encode()),
        IncomingFile("rc.txt", b"Certificate of Registration registration no HR26 AB 1234 chassis number MA3ERLF1S00123456 engine number K12MN1234567"),
        IncomingFile("policy.txt", f"Insurance Policy policy number POL/2023/00845672 period of insurance {policy_period} vehicle HR26 AB 1234".encode()),
        IncomingFile("licence.txt", b"Driving Licence licence number HR-0619850012345 valid till 19 January 2036"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost INR 42000 labour charges INR 8000 vehicle HR26 AB 1234"),
    ]


def test_policy_gate_accepts_policy_active_on_loss_date():
    items = _documents(accident_date="02 November 2023", policy_period="01 January 2023 to 31 December 2023")
    triage = build_triage_result(validate_claim("CLM-POLICY-1", items), items)

    result = apply_policy_validation(triage)

    assert result.policy_validation is not None
    assert result.policy_validation.status == PolicyValidationStatus.VALID
    assert result.policy_validation.policy_number == "POL/2023/00845672"


def test_invalid_policy_retains_reviewer_brief_and_routes_to_single_adjuster():
    items = _documents(accident_date="02 November 2023", policy_period="01 January 2022 to 31 December 2022")

    workflow = run_claim_workflow("CLM-POLICY-2", items)
    result = workflow["triage"]

    assert result.policy_validation is not None
    assert result.policy_validation.status == PolicyValidationStatus.INVALID
    assert result.policy_validation.recommended_action == "REJECT_CLAIM"
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert result.coverage_decision == "NOT_COVERED"
    # Policy eligibility remains the deterministic rejection recommendation,
    # while fraud and assessment agents still create a factual decision brief
    # for the Claims Adjuster.
    assert result.assessment is not None
    assert "Claim CLM-POLICY-2" in result.assessment.case_summary
    assert result.settlement_recommendation is not None
    assert result.settlement_recommendation.status == "NOT_RECOMMENDED"
    assert workflow["human_stage"] == "CLAIMS_ADJUSTER_REVIEW"
