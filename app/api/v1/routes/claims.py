from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from app.schemas.claim_storage import ClaimStorageResponse
from app.schemas.classification import ClassificationCategory, ClassificationResponse
from app.schemas.documents import DocumentType, ReviewDecisionRequest
from app.schemas.rag import AskClaimRequest, IngestResponse
from app.services.document_classifier import UploadedDoc, classify_documents
from app.services.claim_storage import (
    get_all_claims_json_from_postgres,
    get_claim_details_json_from_postgres,
    save_completed_workflow_report,
    store_claim_files_and_metadata,
)
from app.services.rag_service import ingest_policy_data, stream_claim_details
from app.services.triage import triage_claim
from app.services.validator import IncomingFile, validate_claim
from app.services.workflow import run_claim_workflow
from app.core.config import settings

router = APIRouter(prefix="/claims", tags=["claims"])


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
async def get_claim_review_tasks(claim_id: str):
    """List durable Claims Adjuster review tasks for a claim."""
    from app.services.review import list_review_tasks
    return list_review_tasks(claim_id)


@router.post("/reviews/{task_id}/decision")
async def submit_review_decision(task_id: str, request: ReviewDecisionRequest):
    """Resolve the single Claims Adjuster review and record its controlled outcome."""
    from app.services.review import resolve_review_task
    try:
        return resolve_review_task(task_id, request.action, request.reviewer_id, request.comment)
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
    files: list[UploadFile] = File(..., description="One or more files (pictures, PDFs, documents)"),
    claim_id: str | None = Form(None, description="Optional unique claim ID. Generated automatically if omitted."),
    user_name: str | None = Form(None, description="Optional user or claimant name associated with the claim."),
    description: str | None = Form(None, description="Optional claim description."),
    claim_status: str | None = Form("PENDING_VERIFICATION", description="Initial claim status."),
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
        return store_claim_files_and_metadata(
            files=file_tuples,
            claim_id=claim_id,
            user_name=user_name,
            description=description,
            status=claim_status,
        )
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
def get_all_claims() -> list[dict]:
    return get_all_claims_json_from_postgres()


@router.get(
    "/{claim_id}/details",
    response_model=dict,
    summary="Get claim details JSON by claim_id from PostgreSQL",
    description="Retrieves the claim details JSON stored under the claim_folder_json column from Azure PostgreSQL.",
)
def get_claim_details(claim_id: str) -> dict:
    details = get_claim_details_json_from_postgres(claim_id)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim details for {claim_id} not found in database.",
        )
    return details


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Ingest policy details JSON, apply semantic chunking, and index into vector store",
    description=(
        "Loads policy details from Data/Rag/Policu_details.json (or configured path), "
        "applies LangChain's SemanticChunker using Azure OpenAI text_embedding_small model, "
        "and indexes the chunks into a vector store."
    ),
)
@router.post(
    "/rag/ingest",
    response_model=IngestResponse,
    include_in_schema=False,
)
async def ingest_policies() -> IngestResponse:
    try:
        policies_count, chunks_count = ingest_policy_data()
        return IngestResponse(
            status="success",
            policies_loaded=policies_count,
            chunks_created=chunks_count,
            message=(
                f"Successfully loaded {policies_count} policies, applied semantic chunking "
                f"to create {chunks_count} chunks, and indexed into vector store."
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest policy documents: {str(exc)}",
        ) from exc


@router.post(
    "/askClaimDetails",
    summary="Ask claim or policy question with streaming response",
    description=(
        "Retrieves the most semantically relevant policy chunks from the vector store, "
        "invokes the LangChain RAG chain with Azure OpenAI model, and streams the answer token by token."
    ),
)
async def ask_claim_details(request: AskClaimRequest):
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string cannot be empty.",
        )

    async def event_generator():
        try:
            async for token in stream_claim_details(request.query, k=request.k):
                yield token
        except Exception as exc:
            yield f"\n[Error generating response: {str(exc)}]"

    return StreamingResponse(
        event_generator(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/askClaimDetails",
    summary="Ask claim question via GET for quick testing with streaming response",
    include_in_schema=False,
)
async def ask_claim_details_get(query: str = Query(..., min_length=1), k: int = Query(3, ge=1, le=10)):
    return await ask_claim_details(AskClaimRequest(query=query, k=k))


