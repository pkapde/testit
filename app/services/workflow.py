"""LangGraph orchestration for the deterministic intake and triage stages."""
from typing import Literal, TypedDict
from langgraph.graph import END, START, StateGraph
from app.infrastructure.observability import trace_triage
from app.schemas.documents import ClaimTriageResult, ClaimValidationResult, TriageQueue
from app.services.triage import build_triage_result
from app.services.validator import IncomingFile, validate_claim


class ClaimWorkflowState(TypedDict, total=False):
    claim_id: str
    items: list[IncomingFile]
    validation: ClaimValidationResult
    triage: ClaimTriageResult
    human_stage: str
    trace_id: str | None


def validate_documents(state: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"validation": validate_claim(state["claim_id"], state["items"])}


def triage_documents(state: ClaimWorkflowState) -> ClaimWorkflowState:
    result = build_triage_result(state["validation"], state["items"])
    return {"triage": result}


def validate_policy_eligibility(state: ClaimWorkflowState) -> ClaimWorkflowState:
    """Policy Eligibility Gate: run before fraud and all later claim agents."""
    from app.services.policy_validation import apply_policy_validation

    return {"triage": apply_policy_validation(state["triage"])}


def route_after_policy_validation(state: ClaimWorkflowState) -> Literal["fraud_detection", "claims_adjuster_review"]:
    """Do not run fraud/coverage/assessment for invalid or incomplete policy evidence."""
    policy_validation = state["triage"].policy_validation
    if policy_validation and policy_validation.status.value == "VALID":
        return "fraud_detection"
    return "claims_adjuster_review"


def detect_fraud(state: ClaimWorkflowState) -> ClaimWorkflowState:
    """Phase 3 fraud-risk agent; records explainable indicators before routing."""
    from app.services.fraud import apply_fraud_assessment

    result = apply_fraud_assessment(state["triage"])
    return {"triage": result, "trace_id": trace_triage(result)}


def assess_coverage(state: ClaimWorkflowState) -> ClaimWorkflowState:
    """Phase 4 baseline policy coverage and rule-engine agent."""
    from app.services.coverage import apply_coverage_assessment

    return {"triage": apply_coverage_assessment(state["triage"])}


def prepare_claim_assessment(state: ClaimWorkflowState) -> ClaimWorkflowState:
    from app.services.assessment import apply_claim_assessment
    return {"triage": apply_claim_assessment(state["triage"])}


def prepare_settlement_recommendation(state: ClaimWorkflowState) -> ClaimWorkflowState:
    from app.services.settlement import apply_settlement_recommendation
    return {"triage": apply_settlement_recommendation(state["triage"])}


def route_human_stage(_: ClaimWorkflowState) -> Literal["claims_adjuster_review"]:
    """All automated paths converge on the one authorised human reviewer.

    `routing_queue` remains in the triage result as an evidence category (for
    example document quality, fraud risk, or coverage). It is not a separate
    human role or a second approval step.
    """
    return "claims_adjuster_review"


def claims_adjuster_review(_: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"human_stage": "CLAIMS_ADJUSTER_REVIEW"}


def create_claim_workflow():
    graph = StateGraph(ClaimWorkflowState)
    graph.add_node("validate", validate_documents)
    graph.add_node("triage", triage_documents)
    graph.add_node("policy_eligibility", validate_policy_eligibility)
    graph.add_node("fraud_detection", detect_fraud)
    graph.add_node("coverage_assessment", assess_coverage)
    graph.add_node("claim_assessment", prepare_claim_assessment)
    graph.add_node("settlement_recommendation", prepare_settlement_recommendation)
    graph.add_node("claims_adjuster_review", claims_adjuster_review)
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "triage")
    graph.add_edge("triage", "policy_eligibility")
    graph.add_conditional_edges("policy_eligibility", route_after_policy_validation)
    graph.add_edge("fraud_detection", "coverage_assessment")
    graph.add_edge("coverage_assessment", "claim_assessment")
    graph.add_edge("claim_assessment", "settlement_recommendation")
    graph.add_conditional_edges("settlement_recommendation", route_human_stage)
    graph.add_edge("claims_adjuster_review", END)
    return graph.compile()


claim_workflow = create_claim_workflow()


def run_claim_workflow(claim_id: str, items: list[IncomingFile]) -> ClaimWorkflowState:
    return claim_workflow.invoke({"claim_id": claim_id, "items": items})
