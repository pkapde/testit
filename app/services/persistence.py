from hashlib import sha256
from app.infrastructure.postgres import AuditEvent, ClaimRecord, DocumentRecord, session_scope
from app.schemas.documents import ClaimTriageResult
from app.services.review import create_document_review_task
from app.services.validator import IncomingFile


def persist_triage_result(result: ClaimTriageResult, items: list[IncomingFile], blob_uris: dict[str, str] | None = None) -> None:
    """Persist metadata and outcomes; original bytes remain in Blob Storage, never PostgreSQL."""
    blob_uris = blob_uris or {}
    by_name = {item.name: item for item in items}
    with session_scope() as session:
        claim = session.get(ClaimRecord, result.validation.claim_id)
        if not claim:
            claim = ClaimRecord(claim_id=result.validation.claim_id, status=result.validation.overall_status)
            session.add(claim)
        else:
            claim.status = result.validation.overall_status
        for outcome in result.validation.files:
            item = by_name[outcome.file_name]
            session.add(DocumentRecord(claim_id=claim.claim_id, file_name=outcome.file_name, sha256=sha256(item.content).hexdigest(), blob_uri=blob_uris.get(outcome.file_name), detected_type=outcome.detected_document.value, status=outcome.status.value, result=outcome.model_dump(mode="json")))
        session.add(AuditEvent(claim_id=claim.claim_id, event_type="CLAIM_TRIAGED", payload=result.model_dump(mode="json")))
    create_document_review_task(result)
