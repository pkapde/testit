"""Phase 3 explainable fraud-risk detection for motor claims.

This agent produces review indicators only. It never labels a claimant as
fraudulent and never approves or rejects a claim.
"""

from app.schemas.documents import ClaimTriageResult, FraudFinding, FraudRiskLevel, TriageQueue


HIGH_RISK_FIELDS = {"vehicle_registration", "accident_date"}


def assess_fraud_risk(result: ClaimTriageResult) -> tuple[FraudRiskLevel, list[FraudFinding]]:
    """Evaluate transparent, reviewable fraud indicators from completed agents.

    The first Phase 3 release intentionally uses only validated agent output;
    future releases can add claims-history, policy, geospatial, image-forensic,
    and external-watchlist tools behind this same contract.
    """
    findings: list[FraudFinding] = []

    for document in result.validation.files:
        if document.status.value == "DUPLICATE":
            findings.append(FraudFinding(
                rule_id="DUPLICATE_DOCUMENT_CONTENT",
                severity="HIGH",
                message="An uploaded document has identical content to another document in this claim package.",
                evidence={"file_name": document.file_name, "duplicate_of": document.duplicate_of or "unknown"},
            ))

    for issue in result.cross_document_issues:
        severity = "HIGH" if issue.field in HIGH_RISK_FIELDS else "MEDIUM"
        findings.append(FraudFinding(
            rule_id=f"CROSS_DOCUMENT_{issue.field.upper()}",
            severity=severity,
            message=issue.message,
            evidence={key: str(value) for key, value in issue.values_by_document.items()},
        ))

    for finding in result.agentic_findings:
        if finding.assessment in {"INCONSISTENT", "NEEDS_REVIEW"}:
            findings.append(FraudFinding(
                rule_id="SEMANTIC_DOCUMENT_ANOMALY",
                severity="MEDIUM",
                message="Semantic consistency review requires human assessment.",
                evidence={"assessment": finding.assessment, "confidence": str(finding.confidence), "rationale": finding.rationale},
            ))

    # Azure OpenAI receives only normalized extracted fields plus the small,
    # explainable signal set above. Its output is advisory and never HIGH risk.
    from app.infrastructure.azure_openai import assess_fraud_hypotheses

    hypotheses = assess_fraud_hypotheses(
        result.extracted_fields,
        [{"rule_id": finding.rule_id, "severity": finding.severity, "message": finding.message} for finding in findings],
    )
    for hypothesis in hypotheses or []:
        findings.append(FraudFinding(
            rule_id="LLM_FRAUD_REVIEW_HYPOTHESIS",
            severity="MEDIUM",
            message=hypothesis["rationale"],
            evidence={
                "indicator": hypothesis["indicator"],
                "confidence": str(hypothesis["confidence"]),
                "recommended_review": hypothesis["recommended_review"],
            },
        ))

    if any(finding.severity == "HIGH" for finding in findings):
        return FraudRiskLevel.HIGH, findings
    if findings:
        return FraudRiskLevel.MEDIUM, findings
    return FraudRiskLevel.LOW, findings


def apply_fraud_assessment(result: ClaimTriageResult) -> ClaimTriageResult:
    """Attach fraud risk and route only a complete package to a fraud reviewer."""
    risk_level, findings = assess_fraud_risk(result)
    updated = result.model_copy(update={"fraud_risk_level": risk_level, "fraud_findings": findings})
    if updated.routing_queue == TriageQueue.DOCUMENT_VERIFICATION:
        return updated
    if risk_level == FraudRiskLevel.HIGH:
        return updated.model_copy(update={
            "routing_queue": TriageQueue.FRAUD_REVIEW,
            "routing_reason": "High-risk fraud indicators require human fraud review before coverage assessment.",
        })
    if risk_level == FraudRiskLevel.MEDIUM and updated.routing_queue == TriageQueue.READY_FOR_EXTRACTION:
        return updated.model_copy(update={
            "routing_queue": TriageQueue.CLAIMS_OFFICER,
            "routing_reason": "Fraud-risk indicators require claims-officer review before coverage assessment.",
        })
    return updated
