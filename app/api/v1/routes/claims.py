import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from app.schemas.claim_storage import ClaimStorageResponse
from app.schemas.classification import ClassificationCategory, ClassificationResponse
from app.schemas.documents import DocumentType, ReviewDecisionRequest
from app.services.document_classifier import UploadedDoc, classify_documents
from app.services.claim_storage import (
    _get_azure_blob_service,
    get_all_claims_json_from_postgres,
    get_claim_details_json_from_postgres,
    save_completed_workflow_report,
    set_claim_processing_status,
    store_claim_files_and_metadata,
)
from app.services.triage import triage_claim
from app.services.validator import IncomingFile, validate_claim
from app.services.workflow import run_claim_workflow
from app.core.config import settings
from app.services.local_auth import CurrentUser, can_access_claim, get_optional_current_user, require_validator

router = APIRouter(prefix="/claims", tags=["claims"])
logger = logging.getLogger(__name__)


def _run_stored_claim_workflow(claim_id: str) -> None:
    """Run the agent workflow after the upload response has returned.

    Files are read from the private Blob manifest, avoiding a second browser-to-
    API upload. The background task has no user-facing authority beyond storing
    the same workflow result that the synchronous triage endpoint produces.
    """
    set_claim_processing_status(claim_id, "UNDER_ASSESSMENT")
    try:
        details = get_claim_details_json_from_postgres(claim_id)
        if not details:
            raise LookupError("Stored claim metadata was not found")
        blob_service = _get_azure_blob_service()
        if not blob_service:
            raise RuntimeError("Azure Storage is not configured")
        container = (details.get("storage_details") or {}).get("container") or settings.azure_storage_container
        items: list[IncomingFile] = []
        for stored_file in [*(details.get("vehicle_pics") or []), *(details.get("other_evidence") or [])]:
            blob_path = stored_file.get("blob_path")
            if not blob_path:
                continue
            content = blob_service.get_blob_client(container=container, blob=blob_path).download_blob().readall()
            items.append(IncomingFile(
                name=stored_file.get("filename") or "unnamed",
                content=content,
                expected=None,
            ))
        if not items:
            raise ValueError("No stored claim documents were available for analysis")
        workflow = run_claim_workflow(claim_id, items)
        result = workflow["triage"]
        save_completed_workflow_report(claim_id, result)
        # The portal resolves the consolidated review task when an adjuster
        # clicks Approve or Reject.  Persist it after asynchronous processing
        # just as the synchronous triage path does; otherwise a completed
        # background workflow has no actionable task for the UI to resolve.
        if settings.database_url:
            from app.services.persistence import persist_triage_result

            persist_triage_result(result, items)
    except Exception as exc:
        logger.exception("Background workflow failed for claim %s", claim_id)
        set_claim_processing_status(claim_id, "ANALYSIS_FAILED", str(exc))


@router.post(
    "/classification",
    response_model=ClassificationResponse,
    summary="Classify document or accident photos using Azure OpenAI",
    description=(
        "Single API to classify uploaded file(s) against a target category_type using Azure OpenAI. "
        "Classifies survey_report (survey report motor insurance), repair_invoice, "
        "repair_estimate (repair estimate details), insurance_policy, claim_form, "
        "registration_certificate (RC), driving_licence (driver licence), or accident_photos (car pic four side). "
        "Returns whether the document is valid for the category, along with description or error details if invalid. "
        "Does not require a claim_id."
    ),
)
async def classify_document(
    category_type: str = Form(
        ...,
        description=(
            "Target document category to validate against. Supported options: "
            "survey_report (survey report motor insurance), repair_invoice, "
            "repair_estimate (repair estimate details), insurance_policy, claim_form, "
            "registration_certificate (rc), driving_licence (driver licence), accident_photos (car pic four side)."
        ),
    ),
    files: list[UploadFile] = File(
        ..., description="One or more uploaded document or image files for classification."
    ),
) -> ClassificationResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be uploaded for classification.",
        )

    try:
        norm_category = ClassificationCategory.normalize(category_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    uploaded_docs: list[UploadedDoc] = []
    for file in files:
        content = await file.read()
        uploaded_docs.append(
            UploadedDoc(
                filename=file.filename or "unnamed",
                content=content,
                content_type=file.content_type,
            )
        )

    response = await classify_documents(
        category_type=norm_category,
        files=uploaded_docs,
    )

    return response


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
    """Run the workflow, save the completed local JSON, and persist review data when configured."""
    items = [IncomingFile(name=file.filename or "unnamed", content=await file.read()) for file in files]
    workflow = run_claim_workflow(claim_id, items)
    result = workflow["triage"]
    save_completed_workflow_report(claim_id, result)
    if settings.database_url:
        from app.services.persistence import persist_triage_result

        persist_triage_result(result, items)
    return result


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
async def get_claim_review_tasks(
    claim_id: str,
    current_user: CurrentUser | None = Depends(get_optional_current_user),
):
    """List durable Claims Adjuster review tasks for a claim."""
    from app.services.review import create_claims_adjuster_review_task, list_review_tasks
    if current_user or settings.auth_required:
        require_validator(current_user)
    tasks = list_review_tasks(claim_id)
    if tasks:
        return tasks

    # Claims completed before asynchronous task persistence was introduced can
    # already have a complete workflow report but no review row.  Create the
    # one durable task lazily so an adjuster can still complete that claim.
    details = get_claim_details_json_from_postgres(claim_id)
    workflow = (details or {}).get("workflow")
    if isinstance(workflow, dict):
        try:
            from app.schemas.documents import ClaimTriageResult

            create_claims_adjuster_review_task(ClaimTriageResult.model_validate(workflow))
            tasks = list_review_tasks(claim_id)
        except Exception:
            logger.exception("Could not restore review task for claim %s", claim_id)
    return tasks


@router.post("/reviews/{task_id}/decision")
async def submit_review_decision(
    task_id: str,
    request: ReviewDecisionRequest,
    current_user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Resolve the single Claims Adjuster review and record its controlled outcome."""
    from app.services.review import resolve_review_task
    try:
        # A signed claimant session must never be able to supply a validator
        # identifier. The unauthenticated fallback exists only while the
        # transition flag remains disabled for legacy demo calls.
        validator = require_validator(current_user) if current_user or settings.auth_required else None
        return resolve_review_task(
            task_id,
            request.action,
            validator.user_id if validator else request.reviewer_id,
            request.comment,
            deductible=request.deductible,
            requested_documents=[document.value for document in request.requested_documents],
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(
    "/upload-to-storage",
    response_model=ClaimStorageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload claim files to Azure Storage and record claim metadata JSON",
    description=(
        "Accepts multiple files (pictures and PDFs) and stores them in Azure Storage under a unique "
        "folder named {claim_id}_{timestamp}. Images/pictures are stored under the vehicle_pics "
        "subfolder, while PDFs and all other files are stored under other_evidence. "
        "Upon completion, stores the complete claim information JSON in root folder "
        "data/Claim_Data/unique_claim_information and returns full metadata."
    ),
)
async def upload_claim_files_to_storage(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="One or more files (pictures, PDFs, documents)"),
    claim_id: str | None = Form(None, description="Optional unique claim ID. Generated automatically if omitted."),
    user_name: str | None = Form(None, description="Optional user or claimant name associated with the claim."),
    description: str | None = Form(None, description="Optional claim description."),
    claim_status: str | None = Form("PENDING_VERIFICATION", description="Initial claim status."),
    current_user: CurrentUser | None = Depends(get_optional_current_user),
) -> ClaimStorageResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided for upload.",
        )
    file_tuples = []
    for file in files:
        content = await file.read()
        file_tuples.append((file.filename or "unnamed", content, file.content_type))

    try:
        response = store_claim_files_and_metadata(
            files=file_tuples,
            claim_id=claim_id,
            user_name=current_user.full_name if current_user else user_name,
            owner_user_id=current_user.user_id if current_user else None,
            description=description,
            status="ANALYSIS_QUEUED",
        )
        background_tasks.add_task(_run_stored_claim_workflow, response.claim_id)
        return response
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[dict],
    summary="Get all claims and their details JSON from PostgreSQL",
    description=(
        "Retrieves all claims and the details JSON stored under the claim_folder_json column "
        "from the Azure PostgreSQL claim_storage_records table."
    ),
)
@router.get(
    "/all",
    response_model=list[dict],
    include_in_schema=False,
)
def get_all_claims(current_user: CurrentUser | None = Depends(get_optional_current_user)) -> list[dict]:
    if current_user and current_user.role.value == "CLAIMANT":
        return get_all_claims_json_from_postgres(owner_user_id=current_user.user_id)
    return get_all_claims_json_from_postgres()


@router.get(
    "/{claim_id}/details",
    response_model=dict,
    summary="Get claim details JSON by claim_id from PostgreSQL",
    description="Retrieves the claim details JSON stored under the claim_folder_json column from Azure PostgreSQL.",
)
def get_claim_details(claim_id: str, current_user: CurrentUser | None = Depends(get_optional_current_user)) -> dict:
    details = get_claim_details_json_from_postgres(claim_id)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim details for {claim_id} not found in database.",
        )
    if not can_access_claim(details, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this claim.")
    return details


@router.get(
    "/{claim_id}/documents/{filename}",
    summary="Download a claim document through the API",
    description=(
        "Streams a document that belongs to a claim from its private Azure Blob container. "
        "The container remains private; callers never need a public Blob URL."
    ),
)
def download_claim_document(
    claim_id: str,
    filename: str,
    current_user: CurrentUser | None = Depends(get_optional_current_user),
) -> Response:
    """Serve an uploaded claim file only when it is listed in that claim's manifest."""
    details = get_claim_details_json_from_postgres(claim_id)
    if not details:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")
    if not can_access_claim(details, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this claim.")

    requested = filename.strip()
    manifest = [*(details.get("vehicle_pics") or []), *(details.get("other_evidence") or [])]
    stored_file = next((item for item in manifest if item.get("filename") == requested), None)
    if not stored_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found for this claim.")

    blob_service = _get_azure_blob_service()
    if not blob_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure Storage is not configured.",
        )

    try:
        container = (details.get("storage_details") or {}).get("container") or settings.azure_storage_container
        blob_path = stored_file.get("blob_path")
        if not container or not blob_path:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document storage metadata is incomplete.")
        content = blob_service.get_blob_client(container=container, blob=blob_path).download_blob().readall()
        return Response(
            content=content,
            media_type=stored_file.get("content_type") or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{requested}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to retrieve the stored document.") from exc


