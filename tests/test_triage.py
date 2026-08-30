from app.services.triage import triage_claim
from app.services.validator import IncomingFile
from app.schemas.documents import TriageQueue


def document(name: str, text: str) -> IncomingFile:
    return IncomingFile(name, text.encode())


def complete_documents(registration: str = "MH12DE1234") -> list[IncomingFile]:
    return [
        document("claim.txt", f"Claim Form claimant date of loss 15 August 2026 accident details vehicle {registration}"),
        document("rc.txt", f"Certificate of Registration registration no chassis number CHS-DEMO-123 engine number ENG-DEMO-123 vehicle class {registration}"),
        document("policy.txt", f"Insurance Policy policy number POL-DEMO-01 period of insurance 01 January 2026 to 31 December 2026 {registration}"),
        document("licence.txt", "Driving Licence licence number DL-DEMO-123 valid till 19 June 2040"),
        document("estimate.txt", f"Garage Estimate repair estimate estimated cost INR 50,000 labour charges INR 8,000 {registration}"),
    ]


def test_complete_consistent_claim_proceeds_to_extraction():
    result = triage_claim("CLM-8", complete_documents())
    assert result.routing_queue == TriageQueue.READY_FOR_EXTRACTION
    assert not result.cross_document_issues


def test_mismatched_vehicle_goes_to_claims_officer():
    items = complete_documents()
    items[-1] = document("estimate.txt", "Garage Estimate repair estimate estimated cost labour charges MH12XX9999")
    result = triage_claim("CLM-9", items)
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert result.cross_document_issues[0].field == "vehicle_registration"


def test_mismatched_owner_name_goes_to_claims_officer():
    items = complete_documents()
    items[0] = document("claim.txt", "Claim Form claimant Priya Sharma date of loss 15 August 2026 accident details vehicle MH12DE1234")
    items[1] = document("rc.txt", "Certificate of Registration registration no chassis number CHS-DEMO-123 engine number ENG-DEMO-123 vehicle class owner name Rahul Sharma MH12DE1234")
    result = triage_claim("CLM-10", items)
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert result.cross_document_issues[0].field == "person_name"


def test_accident_outside_policy_period_goes_to_claims_officer():
    items = complete_documents()
    items[0] = document("claim.txt", "Claim Form claimant date of loss 15 January 2027 accident details vehicle MH12DE1234")
    items[2] = document("policy.txt", "Insurance Policy policy number POL-DEMO-01 period of insurance 01 January 2026 to 31 December 2026 MH12DE1234")
    result = triage_claim("CLM-11", items)
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert any(issue.field == "policy_coverage_period" for issue in result.cross_document_issues)


def test_expired_licence_on_accident_date_goes_to_claims_officer():
    items = complete_documents()
    items[0] = document("claim.txt", "Claim Form claimant date of loss 15 August 2026 accident details vehicle MH12DE1234")
    items[2] = document("policy.txt", "Insurance Policy policy number POL-DEMO-01 period of insurance 01 January 2026 to 31 December 2026 MH12DE1234")
    items[3] = document("licence.txt", "Driving Licence licence number DL-DEMO-123 valid till 14 August 2026")
    result = triage_claim("CLM-12", items)
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert any(issue.field == "licence_validity" for issue in result.cross_document_issues)


def test_large_invoice_variance_goes_to_claims_officer():
    items = complete_documents()
    items.append(document("invoice.txt", "Tax Invoice invoice number INV-DEMO-1 amount payable INR 80,000 MH12DE1234"))
    result = triage_claim("CLM-13", items)
    assert result.routing_queue == TriageQueue.CLAIMS_OFFICER
    assert any(issue.field == "estimate_invoice_variance" for issue in result.cross_document_issues)


def test_missing_core_field_routes_to_document_verification():
    items = complete_documents()
    items[3] = document("licence.txt", "Driving Licence licence number DL-DEMO-123")
    result = triage_claim("CLM-14", items)
    assert result.routing_queue == TriageQueue.DOCUMENT_VERIFICATION
    assert any(issue.file_name == "licence.txt" and issue.field == "licence_valid_till" for issue in result.field_validation_issues)


def test_invalid_policy_period_routes_to_document_verification():
    items = complete_documents()
    items[2] = document("policy.txt", "Insurance Policy policy number POL-DEMO-01 period of insurance 31 December 2026 to 01 January 2026 MH12DE1234")
    result = triage_claim("CLM-15", items)
    assert result.routing_queue == TriageQueue.DOCUMENT_VERIFICATION
    assert any(issue.field == "policy_period" for issue in result.field_validation_issues)
