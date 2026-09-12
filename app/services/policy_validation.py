"""Policy Eligibility Gate run before fraud and downstream claim agents."""

from datetime import date

from app.schemas.documents import (
    ClaimTriageResult,
    CoverageFinding,
    DocumentType,
    CoverageDecision,
    FileStatus,
    PolicyValidationResult,
    PolicyValidationStatus,
    TriageQueue,
)


def _first(result: ClaimTriageResult, key: str) -> str | None:
    return next((fields[key] for fields in result.extracted_fields.values() if fields.get(key)), None)


def _submitted_policy_is_valid(result: ClaimTriageResult) -> bool:
    return any(
        file.detected_document == DocumentType.POLICY and file.status == FileStatus.VALID
        for file in result.validation.files
    )


def _early_coverage_result(
    result: ClaimTriageResult,
    *,
    decision: CoverageDecision,
    outcome: str,
    message: str,
    evidence: dict[str, str],
) -> dict[str, object]:
    """Return a coverage result even when the policy gate stops the workflow.

    Coverage is deliberately not left as ``None`` for a policy-gated claim:
    that made the reviewer UI say "Not assessed" although the policy agent had
    already produced a meaningful result.  The optional LLM explanation only
    translates the deterministic finding into reviewer-friendly wording; it
    cannot change the decision.
    """
    explanation = None
    try:
        from app.infrastructure.azure_openai import explain_coverage
        from app.services.policy_retrieval import retrieve_policy_clauses

        clauses = retrieve_policy_clauses(
            "policy period accident date policy eligibility coverage exclusions"
        )
        explanation = explain_coverage(facts=evidence, clauses=clauses)
    except Exception:
        # An advisory explanation must never block the deterministic gate.
        explanation = None
    return {
        "coverage_decision": decision,
        "coverage_findings": [
            CoverageFinding(
                rule_id="POLICY_ELIGIBILITY_GATE",
                outcome=outcome,
                message=message,
                evidence=evidence,
            )
        ],
        "coverage_explanation": explanation,
    }


def apply_policy_validation(result: ClaimTriageResult) -> ClaimTriageResult:
    """Verify the policy schedule before expensive/downstream agent work.

    The gate is intentionally deterministic and uses only submitted-document
    facts. It does not claim that the insurer's policy administration system
    has been queried, and it never makes an approval or rejection decision.
    """
    policy_number = _first(result, "policy_number")
    start = _first(result, "policy_start_date")
    end = _first(result, "policy_end_date")
    accident_date = _first(result, "accident_date")
    evidence = {
        key: value
        for key, value in {
            "policy_number": policy_number,
            "policy_start_date": start,
            "policy_end_date": end,
            "accident_date": accident_date,
        }.items()
        if value
    }

    if not _submitted_policy_is_valid(result):
        validation = PolicyValidationResult(
            status=PolicyValidationStatus.NEEDS_REVIEW,
            message="A readable, classified insurance policy is required before policy eligibility can be checked.",
            policy_number=policy_number,
            policy_start_date=start,
            policy_end_date=end,
            accident_date=accident_date,
            evidence=evidence,
        )
        return result.model_copy(update={
            "policy_validation": validation,
            **_early_coverage_result(
                result,
                decision=CoverageDecision.NEEDS_REVIEW,
                outcome="NEEDS_REVIEW",
                message="Coverage cannot be assessed until a readable insurance policy is submitted and verified.",
                evidence=evidence,
            ),
            "routing_queue": TriageQueue.DOCUMENT_VERIFICATION,
            "routing_reason": "Policy eligibility could not be checked because the submitted policy is missing, unreadable, or ambiguous.",
        })

    if not (policy_number and start and end and accident_date):
        validation = PolicyValidationResult(
            status=PolicyValidationStatus.NEEDS_REVIEW,
            message="Policy number, policy period, or accident date is missing from the submitted documents.",
            policy_number=policy_number,
            policy_start_date=start,
            policy_end_date=end,
            accident_date=accident_date,
            evidence=evidence,
        )
        return result.model_copy(update={
            "policy_validation": validation,
            **_early_coverage_result(
                result,
                decision=CoverageDecision.NEEDS_REVIEW,
                outcome="NEEDS_REVIEW",
                message="Coverage requires policy number, policy period, and accident-date confirmation from the submitted documents.",
                evidence=evidence,
            ),
            "routing_queue": TriageQueue.DOCUMENT_VERIFICATION,
            "routing_reason": "Policy eligibility needs document verification before downstream claim processing.",
        })

    try:
        policy_start = date.fromisoformat(start)
        policy_end = date.fromisoformat(end)
        loss_date = date.fromisoformat(accident_date)
    except ValueError:
        validation = PolicyValidationResult(
            status=PolicyValidationStatus.NEEDS_REVIEW,
            message="Policy or accident dates could not be interpreted reliably from the submitted documents.",
            policy_number=policy_number,
            policy_start_date=start,
            policy_end_date=end,
            accident_date=accident_date,
            evidence=evidence,
        )
        return result.model_copy(update={
            "policy_validation": validation,
            **_early_coverage_result(
                result,
                decision=CoverageDecision.NEEDS_REVIEW,
                outcome="NEEDS_REVIEW",
                message="Coverage requires human confirmation because the submitted policy or accident dates could not be interpreted reliably.",
                evidence=evidence,
            ),
            "routing_queue": TriageQueue.DOCUMENT_VERIFICATION,
            "routing_reason": "Policy eligibility needs document verification before downstream claim processing.",
        })

    if policy_start > policy_end:
        validation = PolicyValidationResult(
            status=PolicyValidationStatus.INVALID,
            message="Submitted policy period is invalid because the start date is after the end date.",
            policy_number=policy_number,
            policy_start_date=start,
            policy_end_date=end,
            accident_date=accident_date,
            recommended_action="REQUEST_REUPLOAD",
            evidence=evidence,
        )
        return result.model_copy(update={
            "policy_validation": validation,
            **_early_coverage_result(
                result,
                decision=CoverageDecision.NEEDS_REVIEW,
                outcome="NEEDS_REVIEW",
                message="Coverage is on hold until the policy schedule is resubmitted with a valid start and end date.",
                evidence=evidence,
            ),
            "routing_queue": TriageQueue.DOCUMENT_VERIFICATION,
            "routing_reason": "Submitted policy dates are invalid and require Claims Adjuster review before further processing.",
        })

    if not policy_start <= loss_date <= policy_end:
        validation = PolicyValidationResult(
            status=PolicyValidationStatus.INVALID,
            message="The reported accident date falls outside the submitted policy period.",
            policy_number=policy_number,
            policy_start_date=start,
            policy_end_date=end,
            accident_date=accident_date,
            recommended_action="REJECT_CLAIM",
            evidence=evidence,
        )
        return result.model_copy(update={
            "policy_validation": validation,
            **_early_coverage_result(
                result,
                decision=CoverageDecision.NOT_COVERED,
                outcome="NOT_COVERED",
                message="The submitted policy schedule does not cover the reported accident date; recommend rejection subject to Claims Adjuster confirmation.",
                evidence=evidence,
            ),
            "routing_queue": TriageQueue.CLAIMS_OFFICER,
            "routing_reason": "Policy schedule does not cover the reported accident date; rejection is recommended for Claims Adjuster approval.",
        })

    validation = PolicyValidationResult(
        status=PolicyValidationStatus.VALID,
        message="Submitted policy schedule is active on the reported accident date.",
        policy_number=policy_number,
        policy_start_date=start,
        policy_end_date=end,
        accident_date=accident_date,
        evidence=evidence,
    )
    return result.model_copy(update={"policy_validation": validation})
