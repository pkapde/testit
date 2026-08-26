from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from app.schemas.documents import DocumentType
from app.services.validator import IncomingFile, validate_claim

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
