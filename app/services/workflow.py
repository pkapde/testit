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


def detect_fraud(state: ClaimWorkflowState) -> ClaimWorkflowState:
    """Phase 3 fraud-risk agent; records explainable indicators before routing."""
    from app.services.fraud import apply_fraud_assessment

    result = apply_fraud_assessment(state["triage"])
    return {"triage": result, "trace_id": trace_triage(result)}


def route_human_stage(state: ClaimWorkflowState) -> Literal["document_verification", "claims_officer", "ready_for_extraction"]:
    queue = state["triage"].routing_queue
    if queue == TriageQueue.DOCUMENT_VERIFICATION:
        return "document_verification"
    if queue == TriageQueue.FRAUD_REVIEW:
        return "fraud_review"
    if queue == TriageQueue.CLAIMS_OFFICER:
        return "claims_officer"
    return "ready_for_extraction"


def document_verification(_: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"human_stage": "HUMAN_REVIEW_1_DOCUMENT_VERIFICATION"}


def claims_officer(_: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"human_stage": "HUMAN_REVIEW_2_CLAIMS_OFFICER"}


def fraud_review(_: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"human_stage": "HUMAN_REVIEW_1_FRAUD_REVIEW"}


def ready_for_extraction(_: ClaimWorkflowState) -> ClaimWorkflowState:
    return {"human_stage": "READY_FOR_EXTRACTION"}


def create_claim_workflow():
    graph = StateGraph(ClaimWorkflowState)
    graph.add_node("validate", validate_documents)
    graph.add_node("triage", triage_documents)
    graph.add_node("fraud_detection", detect_fraud)
    graph.add_node("document_verification", document_verification)
    graph.add_node("claims_officer", claims_officer)
    graph.add_node("fraud_review", fraud_review)
    graph.add_node("ready_for_extraction", ready_for_extraction)
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "triage")
    graph.add_edge("triage", "fraud_detection")
    graph.add_conditional_edges("fraud_detection", route_human_stage)
    graph.add_edge("document_verification", END)
    graph.add_edge("claims_officer", END)
    graph.add_edge("fraud_review", END)
    graph.add_edge("ready_for_extraction", END)
    return graph.compile()


claim_workflow = create_claim_workflow()


def run_claim_workflow(claim_id: str, items: list[IncomingFile]) -> ClaimWorkflowState:
    return claim_workflow.invoke({"claim_id": claim_id, "items": items})
