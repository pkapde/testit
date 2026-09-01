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


class TriageQueue(str, Enum):
    DOCUMENT_VERIFICATION = "DOCUMENT_VERIFICATION"
    FRAUD_REVIEW = "FRAUD_REVIEW"
    READY_FOR_EXTRACTION = "READY_FOR_EXTRACTION"
    CLAIMS_OFFICER = "CLAIMS_OFFICER"


class ReviewTaskStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ReviewAction(str, Enum):
    VERIFIED = "VERIFIED"
    REQUEST_REUPLOAD = "REQUEST_REUPLOAD"
    REJECT_DOCUMENT = "REJECT_DOCUMENT"
    ESCALATE_FRAUD = "ESCALATE_FRAUD"
    OVERRIDE = "OVERRIDE"


class ReviewDecisionRequest(BaseModel):
    action: ReviewAction
    reviewer_id: str = Field(min_length=1, max_length=100)
    comment: str = Field(min_length=3, max_length=2000)


class ReviewTaskResponse(BaseModel):
    task_id: str
    claim_id: str
    stage: str
    status: ReviewTaskStatus
    reason: str
    evidence: dict = Field(default_factory=dict)
    decision: ReviewAction | None = None
    reviewer_id: str | None = None
    comment: str | None = None
    resumed_to: str | None = None


class CrossDocumentIssue(BaseModel):
    field: str
    values_by_document: dict[str, str]
    severity: str
    message: str


class FieldValidationIssue(BaseModel):
    file_name: str
    field: str
    severity: str
    message: str


class AgenticFinding(BaseModel):
    field: str
    assessment: str
    confidence: float = Field(ge=0, le=1)
    rationale: str


class FraudRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FraudFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    evidence: dict[str, str] = Field(default_factory=dict)


class ClaimTriageResult(BaseModel):
    validation: ClaimValidationResult
    extracted_fields: dict[str, dict[str, str]]
    extraction_method_by_document: dict[str, str] = Field(default_factory=dict)
    field_validation_issues: list[FieldValidationIssue] = Field(default_factory=list)
    cross_document_issues: list[CrossDocumentIssue] = Field(default_factory=list)
    agentic_findings: list[AgenticFinding] = Field(default_factory=list)
    fraud_risk_level: FraudRiskLevel = FraudRiskLevel.LOW
    fraud_findings: list[FraudFinding] = Field(default_factory=list)
    routing_queue: TriageQueue
    routing_reason: str
