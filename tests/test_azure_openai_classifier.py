from app.infrastructure import azure_openai
from app.schemas.documents import DocumentType


def test_azure_openai_classifier_returns_none_without_configuration(monkeypatch):
    monkeypatch.setattr(azure_openai, "is_configured", lambda: False)
    assert azure_openai.classify_document(file_name="damage.jpg", content=b"image", extracted_text="") is None


def test_azure_openai_classifier_result_is_used_for_ambiguous_image(monkeypatch):
    from app.services.validator import IncomingFile, validate_claim

    monkeypatch.setattr(azure_openai, "is_configured", lambda: True)
    monkeypatch.setattr(
        azure_openai,
        "classify_document",
        lambda **_: (DocumentType.ACCIDENT_PHOTOS, 0.9, ["Visible vehicle body damage"]),
    )
    result = validate_claim("CLM-VISION", [IncomingFile("damage.jpg", b"not-a-real-image")])
    assert result.files[0].detected_document == DocumentType.ACCIDENT_PHOTOS
    assert result.files[0].status.value == "VALID"
    assert "Azure OpenAI fallback classification" in result.files[0].evidence


def test_azure_openai_extraction_augments_missing_deterministic_fields(monkeypatch):
    from app.services.triage import triage_claim
    from app.services.validator import IncomingFile

    monkeypatch.setattr(azure_openai, "is_configured", lambda: True)
    monkeypatch.setattr(
        azure_openai,
        "extract_document_fields",
        lambda **_: {"policy_number": "POL-LLM-001", "policy_start_date": "01 January 2026", "policy_end_date": "31 December 2026"},
    )
    files = [
        IncomingFile("claim.txt", b"Claim Form claimant date of loss 15 August 2026 accident details MH12DE1234"),
        IncomingFile("rc.txt", b"Certificate of Registration registration no chassis no vehicle class MH12DE1234"),
        IncomingFile("policy.txt", b"Insurance Policy policy schedule MH12DE1234"),
        IncomingFile("licence.txt", b"Driving Licence licence number DL-DEMO-1 valid till 19 June 2040"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost labour charges MH12DE1234"),
    ]
    result = triage_claim("CLM-LLM", files)
    assert result.extracted_fields["policy.txt"]["policy_number"] == "POL-LLM-001"
    assert result.extraction_method_by_document["policy.txt"] == "DETERMINISTIC_PLUS_AZURE_OPENAI"


def test_azure_openai_extraction_marks_deterministic_values_as_verified(monkeypatch):
    from app.services.triage import _augment_with_llm
    from app.services.validator import IncomingFile

    monkeypatch.setattr(azure_openai, "is_configured", lambda: True)
    monkeypatch.setattr(azure_openai, "extract_document_fields", lambda **_: {"policy_number": "POL-DEMO-001"})
    method = _augment_with_llm({"policy_number": "POL-DEMO-001"}, IncomingFile("policy.txt", b"text"), DocumentType.POLICY, "Insurance Policy")
    assert method == "DETERMINISTIC_VERIFIED_BY_AZURE_OPENAI"


def test_agentic_cross_document_finding_routes_to_claims_officer(monkeypatch):
    from app.services.triage import triage_claim
    from app.services.validator import IncomingFile

    monkeypatch.setattr(azure_openai, "assess_cross_document_consistency", lambda _: [
        {"field": "accident_details", "assessment": "NEEDS_REVIEW", "confidence": 0.82, "rationale": "Narratives describe different impact locations."}
    ])
    files = [
        IncomingFile("claim.txt", b"Claim Form claimant date of loss 15 August 2026 accident details front impact MH12DE1234"),
        IncomingFile("rc.txt", b"Certificate of Registration registration no chassis number CHS-DEMO-123 engine number ENG-DEMO-123 vehicle class MH12DE1234"),
        IncomingFile("policy.txt", b"Insurance Policy policy number POL-DEMO-01 period of insurance 01 January 2026 to 31 December 2026 MH12DE1234"),
        IncomingFile("licence.txt", b"Driving Licence licence number DL-DEMO-123 valid till 19 June 2040"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost INR 50,000 labour charges INR 8,000 MH12DE1234"),
    ]
    result = triage_claim("CLM-CROSS-LLM", files)
    assert result.routing_queue.value == "CLAIMS_OFFICER"
    assert result.agentic_findings[0].assessment == "NEEDS_REVIEW"
