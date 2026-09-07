"""Phase 4 deterministic coverage and rule-engine checks.

These are baseline rules only. Insurer-specific clauses, endorsements, limits,
and deductibles must be configured from approved policy wording.
"""
from datetime import date
from app.schemas.documents import ClaimTriageResult, CoverageDecision, CoverageFinding, TriageQueue


def _first(result: ClaimTriageResult, key: str) -> str | None:
    return next((fields[key] for fields in result.extracted_fields.values() if fields.get(key)), None)


def apply_coverage_assessment(result: ClaimTriageResult) -> ClaimTriageResult:
    findings: list[CoverageFinding] = []
    start, end, loss_date = _first(result, "policy_start_date"), _first(result, "policy_end_date"), _first(result, "accident_date")
    if not (start and end and loss_date):
        findings.append(CoverageFinding(rule_id="POLICY_PERIOD_AVAILABLE", outcome="NEEDS_REVIEW", message="Policy period or accident date is unavailable for a coverage check."))
    elif not date.fromisoformat(start) <= date.fromisoformat(loss_date) <= date.fromisoformat(end):
        findings.append(CoverageFinding(rule_id="POLICY_ACTIVE_ON_LOSS_DATE", outcome="NOT_COVERED", message="Reported accident date falls outside the submitted policy period.", evidence={"policy_start_date": start, "policy_end_date": end, "accident_date": loss_date}))
    else:
        findings.append(CoverageFinding(rule_id="POLICY_ACTIVE_ON_LOSS_DATE", outcome="PASS", message="Submitted policy covers the reported accident date."))

    licence_end = _first(result, "licence_valid_till")
    if loss_date and licence_end and date.fromisoformat(loss_date) > date.fromisoformat(licence_end):
        findings.append(CoverageFinding(rule_id="LICENCE_VALID_ON_LOSS_DATE", outcome="NEEDS_REVIEW", message="Driving licence was expired on the reported accident date.", evidence={"licence_valid_till": licence_end, "accident_date": loss_date}))

    idv, estimate = _first(result, "insured_declared_value"), _first(result, "estimate_total")
    if idv and estimate and float(estimate) > float(idv):
        findings.append(CoverageFinding(rule_id="ESTIMATE_WITHIN_IDV", outcome="NEEDS_REVIEW", message="Garage estimate exceeds the submitted insured declared value.", evidence={"insured_declared_value": idv, "estimate_total": estimate}))

    decision = CoverageDecision.NOT_COVERED if any(item.outcome == "NOT_COVERED" for item in findings) else CoverageDecision.NEEDS_REVIEW if any(item.outcome == "NEEDS_REVIEW" for item in findings) else CoverageDecision.ELIGIBLE_FOR_REVIEW
    from app.infrastructure.azure_openai import explain_coverage
    from app.services.policy_retrieval import retrieve_policy_clauses
    facts = {key: value for fields in result.extracted_fields.values() for key, value in fields.items() if key in {"accident_date", "policy_start_date", "policy_end_date", "licence_valid_till", "insured_declared_value", "estimate_total"}}
    clauses = retrieve_policy_clauses("policy period accident date driving licence insured declared value estimate exclusions")
    explanation = explain_coverage(facts=facts, clauses=clauses)
    updated = result.model_copy(update={"coverage_decision": decision, "coverage_findings": findings, "coverage_explanation": explanation})
    if updated.routing_queue == TriageQueue.READY_FOR_EXTRACTION and decision != CoverageDecision.ELIGIBLE_FOR_REVIEW:
        return updated.model_copy(update={"routing_queue": TriageQueue.CLAIMS_OFFICER, "routing_reason": "Coverage-rule findings require claims-officer review; no automatic denial is made."})
    return updated
