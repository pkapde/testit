"""Phase 5 claims assessment and review-report preparation."""
from app.schemas.documents import ClaimAssessment, ClaimTriageResult, TriageQueue


def apply_claim_assessment(result: ClaimTriageResult) -> ClaimTriageResult:
    """Build a review-ready summary; this agent makes no claim decision."""
    if result.routing_queue in {TriageQueue.DOCUMENT_VERIFICATION, TriageQueue.FRAUD_REVIEW}:
        return result
    extracted_count = sum(len(fields) for fields in result.extracted_fields.values())
    evidence = [f"{item.file_name}: {item.detected_document.value}" for item in result.validation.files if item.status.value == "VALID"]
    checklist = [finding.message for finding in result.coverage_findings if finding.outcome != "PASS"]
    checklist.extend(finding.message for finding in result.fraud_findings)
    checklist.extend(issue.message for issue in result.cross_document_issues)
    summary = f"Claim {result.validation.claim_id} contains {len(evidence)} validated document(s) and {extracted_count} extracted field(s). Routing: {result.routing_queue.value}."
    method = "DETERMINISTIC"

    from app.infrastructure.azure_openai import generate_claim_assessment
    ai_assessment = generate_claim_assessment(summary=summary, evidence=evidence, checklist=checklist)
    if ai_assessment:
        summary = ai_assessment.get("case_summary", summary)
        checklist = ai_assessment.get("reviewer_checklist", checklist)
        method = "DETERMINISTIC_PLUS_AZURE_OPENAI"
    assessment = ClaimAssessment(case_summary=summary, evidence_summary=evidence, reviewer_checklist=checklist[:10], generation_method=method)
    return result.model_copy(update={"assessment": assessment})
