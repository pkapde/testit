from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Iterable
from app.core.config import settings
from app.schemas.documents import ClaimValidationResult, DocumentType, FileStatus, FileValidationResult
from app.services.classifier import classify_text

DEFAULT_REQUIRED = [DocumentType.CLAIM_FORM, DocumentType.RC, DocumentType.POLICY, DocumentType.DRIVING_LICENCE, DocumentType.GARAGE_ESTIMATE]
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".jpg", ".jpeg", ".png"}


@dataclass
class IncomingFile:
    name: str
    content: bytes
    expected: DocumentType | None = None


def _extract_text(item: IncomingFile) -> tuple[str | None, str | None]:
    extension = Path(item.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return None, f"Unsupported file type: {extension or 'no extension'}"
    if not item.content:
        return None, "File is empty"
    if len(item.content) > settings.max_upload_size_bytes:
        return None, "File exceeds configured upload size limit"
    if extension == ".txt":
        return item.content.decode("utf-8", errors="replace"), None
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(item.content)).pages)
            if text.strip():
                return text, None
        except Exception:
            return None, "PDF could not be read"
    if settings.document_intelligence_endpoint:
        try:
            from app.infrastructure.document_intelligence import extract_document_text
            text = extract_document_text(item.content)
            return text, None if text.strip() else "OCR returned no readable text; manual review required"
        except Exception:
            return None, "OCR could not read this document; manual review required"
    if extension == ".pdf":
        return None, "PDF has no extractable text. It may be a scanned PDF and requires OCR."
    # An image can still be classified by a vision-capable Azure OpenAI deployment.
    return "", None


def validate_claim(claim_id: str, items: Iterable[IncomingFile], required_documents: list[DocumentType] | None = None) -> ClaimValidationResult:
    required, results, hashes, valid_detected = required_documents or DEFAULT_REQUIRED, [], {}, set()
    for item in items:
        digest = sha256(item.content).hexdigest()
        if digest in hashes:
            results.append(FileValidationResult(file_name=item.name, expected_document=item.expected, status=FileStatus.DUPLICATE, message=f"Duplicate content of {hashes[digest]}", classification_confidence=0.0, duplicate_of=hashes[digest]))
            continue
        hashes[digest] = item.name
        text, error = _extract_text(item)
        if error:
            review_required = "OCR" in error
            results.append(FileValidationResult(file_name=item.name, expected_document=item.expected, status=FileStatus.NEEDS_REVIEW if review_required else FileStatus.UNREADABLE, message=error, classification_confidence=0.0))
            continue
        detected, confidence, evidence = classify_text(text or "")
        extension = Path(item.name).suffix.lower()
        use_ai_fallback = extension in {".jpg", ".jpeg", ".png"} or detected == DocumentType.UNKNOWN or confidence < settings.classification_review_threshold
        if use_ai_fallback:
            from app.infrastructure.azure_openai import classify_document, is_configured
            ai_result = classify_document(file_name=item.name, content=item.content, extracted_text=text or "")
            if ai_result:
                detected, confidence, evidence = ai_result
                evidence = ["Azure OpenAI fallback classification"] + evidence
            elif detected == DocumentType.UNKNOWN and is_configured():
                evidence = ["Azure OpenAI classification did not return a usable result"]
        if detected == DocumentType.UNKNOWN or confidence < settings.classification_review_threshold:
            status, message = FileStatus.NEEDS_REVIEW, "Document type is ambiguous; manual review required"
        elif item.expected and detected != item.expected:
            status, message = FileStatus.WRONG_DOCUMENT, f"Expected {item.expected.value}, but content indicates {detected.value}"
        else:
            status, message = FileStatus.VALID, "Document content matches the expected type" if item.expected else "Document classified successfully"
            valid_detected.add(detected)
        results.append(FileValidationResult(file_name=item.name, expected_document=item.expected, detected_document=detected, classification_confidence=confidence, status=status, message=message, evidence=evidence))
    missing = [doc for doc in required if doc not in valid_detected]
    invalid = sum(result.status != FileStatus.VALID for result in results)
    return ClaimValidationResult(claim_id=claim_id, required_documents=required, missing_documents=missing, documents_received=len(results), valid_documents=len(results) - invalid, invalid_documents=invalid, overall_status="COMPLETE" if not missing and not invalid else "NEEDS_CORRECTION", files=results)
