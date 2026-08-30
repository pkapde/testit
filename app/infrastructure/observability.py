"""Sanitized workflow tracing. PostgreSQL remains the system of record for audit events."""
from uuid import uuid4
from app.core.config import settings
from app.infrastructure.secrets import get_secret
from app.schemas.documents import ClaimTriageResult


def trace_triage(result: ClaimTriageResult) -> str | None:
    """Emit a LangSmith trace without sending original document bytes or extracted PII."""
    key = get_secret(settings.langsmith_api_key_secret_name or "", settings.langsmith_api_key)
    if not (settings.langsmith_tracing and key):
        return None
    from langsmith import Client
    run_id = uuid4()
    Client(api_key=key).create_run(
        id=run_id,
        name="contractiq-claim-triage",
        run_type="chain",
        project_name=settings.langsmith_project,
        inputs={"claim_id": result.validation.claim_id, "document_count": result.validation.documents_received},
        outputs={"overall_status": result.validation.overall_status, "routing_queue": result.routing_queue.value, "issue_count": len(result.cross_document_issues)},
    )
    return str(run_id)
