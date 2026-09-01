from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from app.schemas.documents import DocumentType, ReviewDecisionRequest
from app.services.triage import triage_claim
from app.services.validator import IncomingFile, validate_claim
from app.services.workflow import run_claim_workflow

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("/{claim_id}/validate")
async def validate_claim_documents(
    claim_id: str,
    files: list[UploadFile] = File(...),
    expected_documents: str | None = Form(None),
):
    """Validate a motor-claim document package; this endpoint never settles a claim."""
    expected_values = [value.strip() for value in expected_documents.split(",")] if expected_documents else []
    if expected_values and len(expected_values) != len(files):
        raise HTTPException(422, "expected_documents must have one value per uploaded file")
    try:
        expected = [DocumentType(value) for value in expected_values]
    except ValueError as exc:
        raise HTTPException(422, f"Unknown expected document type: {exc}") from exc
    items = [
        IncomingFile(
            name=file.filename or "unnamed",
            content=await file.read(),
            expected=expected[index] if expected else None,
        )
        for index, file in enumerate(files)
    ]
    return validate_claim(claim_id, items)


@router.post("/{claim_id}/classification-completeness", response_model=None)
async def classify_and_check_completeness(
    claim_id: str,
    files: list[UploadFile] = File(...),
    expected_documents: str | None = Form(None),
):
    """Run Agent 1 only: file checks, document classification, duplicates, and completeness.

    This is the UI integration endpoint. It deliberately stops before Phase 2
    extraction and cross-document consistency checks. `expected_documents` is
    optional and accepts a comma-separated value per file, for example
    `fir,accident_photos`.
    """
    expected_values = [value.strip() for value in expected_documents.split(",")] if expected_documents else []
    if expected_values and len(expected_values) != len(files):
        raise HTTPException(422, "expected_documents must have one value per uploaded file")
    try:
        expected = [DocumentType(value) for value in expected_values]
    except ValueError as exc:
        raise HTTPException(422, f"Unknown expected document type: {exc}") from exc

    items = [
        IncomingFile(
            name=file.filename or "unnamed",
            content=await file.read(),
            expected=expected[index] if expected else None,
        )
        for index, file in enumerate(files)
    ]
    return validate_claim(claim_id, items)


@router.post("/{claim_id}/triage")
async def triage_claim_documents(claim_id: str, files: list[UploadFile] = File(...)):
    """Validate, extract basic identifiers, cross-check them, and route to a human stage."""
    items = [IncomingFile(name=file.filename or "unnamed", content=await file.read()) for file in files]
    workflow = run_claim_workflow(claim_id, items)
    return workflow["triage"]


@router.post("/{claim_id}/ingest")
async def ingest_claim_documents(claim_id: str, files: list[UploadFile] = File(...)):
    """Production integration path: Blob Storage -> validation/triage -> PostgreSQL audit records."""
    from app.infrastructure.blob_storage import upload_claim_document
    from app.services.persistence import persist_triage_result
    items = [IncomingFile(name=file.filename or "unnamed", content=await file.read()) for file in files]
    blob_uris = {}
    for file, item in zip(files, items):
        _, blob_uris[item.name] = upload_claim_document(claim_id, item.name, item.content, file.content_type)
    result = triage_claim(claim_id, items)
    persist_triage_result(result, items, blob_uris)
    return result


@router.get("/{claim_id}/reviews")
async def get_claim_review_tasks(claim_id: str):
    """List durable document-review tasks for a claim."""
    from app.services.review import list_review_tasks
    return list_review_tasks(claim_id)


@router.post("/reviews/{task_id}/decision")
async def submit_review_decision(task_id: str, request: ReviewDecisionRequest):
    """Resolve Human Review #1 and move the claim to its controlled next stage."""
    from app.services.review import resolve_review_task
    try:
        return resolve_review_task(task_id, request.action, request.reviewer_id, request.comment)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
