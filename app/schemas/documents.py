from enum import Enum
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    CLAIM_FORM = "claim_form"
    RC = "rc"
    POLICY = "policy"
    DRIVING_LICENCE = "driving_licence"
    FIR = "fir"
    GARAGE_ESTIMATE = "garage_estimate"
    REPAIR_INVOICE = "repair_invoice"
    ACCIDENT_PHOTOS = "accident_photos"
    UNKNOWN = "unknown"


class FileStatus(str, Enum):
    VALID = "VALID"
    WRONG_DOCUMENT = "WRONG_DOCUMENT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNREADABLE = "UNREADABLE"
    DUPLICATE = "DUPLICATE"


class FileValidationResult(BaseModel):
    file_name: str
    expected_document: DocumentType | None = None
    detected_document: DocumentType = DocumentType.UNKNOWN
    classification_confidence: float = Field(ge=0, le=1)
    status: FileStatus
    message: str
    evidence: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None


class ClaimValidationResult(BaseModel):
    claim_id: str
    required_documents: list[DocumentType]
    missing_documents: list[DocumentType]
    documents_received: int
    valid_documents: int
    invalid_documents: int
    overall_status: str
    files: list[FileValidationResult]
