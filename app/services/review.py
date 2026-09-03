"""Human Review #1 task lifecycle and safe workflow resumption."""
from datetime import datetime, timezone
from uuid import uuid4

from app.infrastructure.postgres import AuditEvent, ClaimRecord, ReviewTaskRecord, session_scope
from app.schemas.documents import ClaimTriageResult, ReviewAction, ReviewTaskResponse, ReviewTaskStatus


NEXT_CLAIM_STATUS: dict[ReviewAction, str] = {
    ReviewAction.VERIFIED: "READY_FOR_EXTRACTION",
    ReviewAction.OVERRIDE: "READY_FOR_EXTRACTION",
    ReviewAction.REQUEST_REUPLOAD: "WAITING_FOR_UPLOAD",
    ReviewAction.REJECT_DOCUMENT: "DOCUMENT_REJECTED",
    ReviewAction.ESCALATE_FRAUD: "FRAUD_REVIEW",
}


def next_claim_status(action: ReviewAction) -> str:
    """Map a human decision to the controlled next workflow stage."""
    return NEXT_CLAIM_STATUS[action]


def _to_response(task: ReviewTaskRecord) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        task_id=task.task_id,
        claim_id=task.claim_id,
        stage=task.stage,
        status=ReviewTaskStatus(task.status),
        reason=task.reason,
        evidence=task.evidence,
        decision=ReviewAction(task.decision) if task.decision else None,
        reviewer_id=task.reviewer_id,
        comment=task.comment,
        resumed_to=task.resumed_to,
    )


def create_document_review_task(result: ClaimTriageResult) -> ReviewTaskResponse | None:
    """Persist a Human Review #1 task for document or high-risk fraud routing."""
    if result.routing_queue.value not in {"DOCUMENT_VERIFICATION", "FRAUD_REVIEW"}:
        return None
    evidence = {
        "validation": result.validation.model_dump(mode="json"),
        "field_validation_issues": [issue.model_dump(mode="json") for issue in result.field_validation_issues],
        "cross_document_issues": [issue.model_dump(mode="json") for issue in result.cross_document_issues],
        "agentic_findings": [finding.model_dump(mode="json") for finding in result.agentic_findings],
    }
    with session_scope() as session:
        stage = (
            "HUMAN_REVIEW_1_FRAUD_REVIEW"
            if result.routing_queue.value == "FRAUD_REVIEW"
            else "HUMAN_REVIEW_1_DOCUMENT_VERIFICATION"
        )
        task = ReviewTaskRecord(
            task_id=str(uuid4()),
            claim_id=result.validation.claim_id,
            stage=stage,
            status=ReviewTaskStatus.OPEN.value,
            reason=result.routing_reason,
            evidence=evidence,
        )
        session.add(task)
        session.add(AuditEvent(claim_id=task.claim_id, event_type="DOCUMENT_REVIEW_TASK_CREATED", payload={"task_id": task.task_id, "reason": task.reason}))
        session.flush()
        return _to_response(task)


def list_review_tasks(claim_id: str) -> list[ReviewTaskResponse]:
    with session_scope() as session:
        tasks = session.query(ReviewTaskRecord).filter_by(claim_id=claim_id).order_by(ReviewTaskRecord.created_at.desc()).all()
        return [_to_response(task) for task in tasks]


def resolve_review_task(task_id: str, action: ReviewAction, reviewer_id: str, comment: str) -> ReviewTaskResponse:
    """Record a human decision and make the claim eligible for its next controlled stage."""
    with session_scope() as session:
        task = session.get(ReviewTaskRecord, task_id)
        if not task:
            raise LookupError("Review task was not found")
        if task.status != ReviewTaskStatus.OPEN.value:
            raise ValueError("Review task has already been resolved")
        resumed_to = next_claim_status(action)
        task.status = ReviewTaskStatus.RESOLVED.value
        task.decision = action.value
        task.reviewer_id = reviewer_id
        task.comment = comment
        task.resumed_to = resumed_to
        task.resolved_at = datetime.now(timezone.utc)
        claim = session.get(ClaimRecord, task.claim_id)
        if claim:
            claim.status = resumed_to
        session.add(AuditEvent(
            claim_id=task.claim_id,
            event_type="DOCUMENT_REVIEW_TASK_RESOLVED",
            payload={"task_id": task.task_id, "action": action.value, "reviewer_id": reviewer_id, "comment": comment, "resumed_to": resumed_to},
        ))
        session.flush()
        return _to_response(task)
