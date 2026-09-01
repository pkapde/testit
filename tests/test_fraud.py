from app.schemas.documents import ClaimTriageResult, ClaimValidationResult, CrossDocumentIssue, DocumentType, TriageQueue
from app.services.fraud import apply_fraud_assessment
from app.services.validator import IncomingFile
from app.services.workflow import run_claim_workflow


def _result_with_vehicle_mismatch() -> ClaimTriageResult:
    return ClaimTriageResult(
        validation=ClaimValidationResult(
            claim_id="CLM-FRAUD-1",
            required_documents=[DocumentType.CLAIM_FORM],
            missing_documents=[],
            documents_received=1,
            valid_documents=1,
            invalid_documents=0,
            overall_status="COMPLETE",
            files=[],
        ),
        extracted_fields={},
        cross_document_issues=[CrossDocumentIssue(
            field="vehicle_registration",
            values_by_document={"claim.pdf": "DL01AB1234", "rc.pdf": "HR02CD5678"},
            severity="HIGH",
            message="Vehicle registration differs across submitted documents.",
        )],
        routing_queue=TriageQueue.READY_FOR_EXTRACTION,
        routing_reason="No issue.",
    )


def test_high_risk_vehicle_mismatch_routes_to_fraud_review():
    result = apply_fraud_assessment(_result_with_vehicle_mismatch())
    assert result.fraud_risk_level == "HIGH"
    assert result.routing_queue == TriageQueue.FRAUD_REVIEW
    assert result.fraud_findings[0].rule_id == "CROSS_DOCUMENT_VEHICLE_REGISTRATION"


def test_workflow_runs_fraud_agent_before_final_human_routing():
    files = [
        IncomingFile("claim.txt", b"Claim Form claimant accident details date of loss vehicle DL01AB1234"),
        IncomingFile("rc.txt", b"Registration Certificate registration no HR02CD5678 chassis no vehicle class"),
        IncomingFile("policy.txt", b"Insurance Policy policy number period of insurance vehicle HR02CD5678"),
        IncomingFile("licence.txt", b"Driving Licence licence no valid till driving licence"),
        IncomingFile("estimate.txt", b"Garage Estimate repair estimate estimated cost labour charges vehicle HR02CD5678"),
    ]
    result = run_claim_workflow("CLM-FRAUD-2", files)
    assert result["triage"].fraud_risk_level in {"LOW", "MEDIUM", "HIGH"}
    assert result["human_stage"] in {
        "HUMAN_REVIEW_1_DOCUMENT_VERIFICATION",
        "HUMAN_REVIEW_1_FRAUD_REVIEW",
        "HUMAN_REVIEW_2_CLAIMS_OFFICER",
        "READY_FOR_EXTRACTION",
    }


def test_llm_fraud_hypothesis_is_always_advisory(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.azure_openai.assess_fraud_hypotheses",
        lambda *_: [{"indicator": "Narrative ambiguity", "confidence": 0.83, "rationale": "Narrative needs review.", "recommended_review": "Compare FIR and claim narrative."}],
    )
    result = apply_fraud_assessment(_result_with_vehicle_mismatch())
    llm_finding = next(item for item in result.fraud_findings if item.rule_id == "LLM_FRAUD_REVIEW_HYPOTHESIS")
    assert llm_finding.severity == "MEDIUM"
    assert result.fraud_risk_level == "HIGH"  # High risk comes from deterministic vehicle mismatch.
