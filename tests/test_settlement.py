from app.services.triage import triage_claim
from app.services.validator import IncomingFile


def test_eligible_claim_has_non_binding_settlement_recommendation():
    files = [
        IncomingFile("claim.txt", b"Claim Form date of loss 15 August 2026 vehicle MH12DE1234"),
        IncomingFile("rc.txt", b"Certificate of Registration registration no MH12DE1234 chassis number CHS1 engine number ENG1"),
        IncomingFile("policy.txt", b"Insurance Policy policy number POL1 period of insurance 01 January 2026 to 31 December 2026 insured declared value INR 100000 MH12DE1234"),
        IncomingFile("licence.txt", b"Driving Licence licence number DL1 valid till 19 June 2040"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost INR 50000 labour charges INR 8000 MH12DE1234"),
    ]
    result = triage_claim("CLM-SET-1", files)
    assert result.settlement_recommendation is not None
    assert result.settlement_recommendation.status == "REVIEW_REQUIRED"
    assert result.settlement_recommendation.preliminary_amount == "50000.00"
