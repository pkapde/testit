"""Phase 6 non-binding settlement recommendation preparation."""
from decimal import Decimal
from app.schemas.documents import ClaimTriageResult, CoverageDecision, SettlementRecommendation


def _first(result: ClaimTriageResult, key: str) -> str | None:
    return next((fields[key] for fields in result.extracted_fields.values() if fields.get(key)), None)


def apply_settlement_recommendation(result: ClaimTriageResult) -> ClaimTriageResult:
    """Prepare a capped preliminary amount; no payment is approved here."""
    if result.coverage_decision != CoverageDecision.ELIGIBLE_FOR_REVIEW:
        recommendation = SettlementRecommendation(status="NOT_RECOMMENDED", basis=["Coverage is not eligible for a preliminary settlement recommendation."])
        return result.model_copy(update={"settlement_recommendation": recommendation})
    estimate, idv = _first(result, "estimate_total"), _first(result, "insured_declared_value")
    if not estimate:
        recommendation = SettlementRecommendation(status="INSUFFICIENT_DATA", basis=["No validated garage estimate is available."])
        return result.model_copy(update={"settlement_recommendation": recommendation})
    amount = Decimal(estimate)
    basis = [f"Validated garage estimate: INR {amount:.2f}"]
    if idv:
        amount = min(amount, Decimal(idv))
        basis.append(f"Submitted IDV cap considered: INR {Decimal(idv):.2f}")
    basis.append("Policy deductible, applicable add-ons, survey assessment, and approved repair scope require human confirmation.")
    explanation = None
    method = "DETERMINISTIC"
    from app.infrastructure.azure_openai import explain_settlement_recommendation
    explanation = explain_settlement_recommendation(preliminary_amount=f"{amount:.2f}", basis=basis)
    if explanation:
        method = "DETERMINISTIC_PLUS_AZURE_OPENAI"
    recommendation = SettlementRecommendation(status="REVIEW_REQUIRED", preliminary_amount=f"{amount:.2f}", basis=basis, explanation=explanation, generation_method=method)
    return result.model_copy(update={"settlement_recommendation": recommendation})
