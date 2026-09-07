from app.services.coverage import apply_coverage_assessment
from app.services.triage import triage_claim
from app.services.validator import IncomingFile
from app.schemas.documents import CoverageDecision, TriageQueue


def test_policy_outside_loss_date_requires_claims_officer_review():
    items = [
        IncomingFile("claim.txt", b"Claim Form date of loss 15 January 2027 vehicle MH12DE1234"),
        IncomingFile("rc.txt", b"Certificate of Registration registration no MH12DE1234 chassis number CHS1 engine number ENG1"),
        IncomingFile("policy.txt", b"Insurance Policy policy number POL1 period of insurance 01 January 2026 to 31 December 2026 MH12DE1234"),
        IncomingFile("licence.txt", b"Driving Licence licence number DL1 valid till 19 June 2040"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost INR 50000 labour charges INR 8000 MH12DE1234"),
    ]
    triage = triage_claim("CLM-COV-1", items)
    result = apply_coverage_assessment(triage)
    assert result.coverage_decision == CoverageDecision.NOT_COVERED
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
