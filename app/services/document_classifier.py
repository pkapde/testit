import base64
from io import BytesIO
import json
import logging
import mimetypes
from typing import NamedTuple

from openai import AzureOpenAI
from pypdf import PdfReader

from app.core.config import settings
from app.infrastructure.secrets import get_secret
from app.schemas.classification import (
    AccidentPhotoCoverage,
    ClassificationCategory,
    ClassificationResponse,
    FileAssessment,
)

logger = logging.getLogger(__name__)


class UploadedDoc(NamedTuple):
    filename: str
    content: bytes
    content_type: str | None = None


def _determine_mime_type(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guess, _ = mimetypes.guess_type(filename)
    if guess:
        return guess
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".txt"):
        return "text/plain"
    return "image/jpeg"


def _extract_text_from_pdf(content: bytes) -> str:
    """Extract text from PDF pages for text analysis."""
    try:
        reader = PdfReader(BytesIO(content))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages_text).strip()
    except Exception as exc:
        logger.warning("Failed to extract text from PDF: %s", exc)
        return ""


def _mock_classification_fallback(
    target_category: ClassificationCategory, files: list[UploadedDoc]
) -> ClassificationResponse:
    """Fallback classifier when Azure OpenAI is not configured or offline."""
    assessments = []
    category_val = target_category.value

    # Quick heuristic check on mock file text / names for offline testing
    all_text = ""
    for file in files:
        mime = _determine_mime_type(file.filename, file.content_type)
        if mime == "application/pdf":
            text = _extract_text_from_pdf(file.content).lower()
        else:
            try:
                text = file.content.decode("utf-8", errors="ignore").lower()
            except Exception:
                text = ""
        all_text += " " + text + " " + file.filename.lower()

    indicators = {
        ClassificationCategory.SURVEY_REPORT: ["survey", "surveyor", "survey report", "loss assessment", "inspection report"],
        ClassificationCategory.REPAIR_INVOICE: ["invoice", "tax invoice", "bill", "gstin", "total value"],
        ClassificationCategory.REPAIR_ESTIMATE: ["estimate", "repair estimate", "estimated cost", "parts total", "labour", "estimate details"],
        ClassificationCategory.GARAGE_ESTIMATE: ["estimate", "repair estimate", "garage", "parts total"],
        ClassificationCategory.INSURANCE_POLICY: ["policy", "insured", "insurance", "premium", "coverage"],
        ClassificationCategory.CLAIM_FORM: ["claim", "claimant", "loss", "accident details"],
        ClassificationCategory.REGISTRATION_CERTIFICATE: ["registration", "rc", "chassis", "engine", "vehicle class"],
        ClassificationCategory.DRIVING_LICENCE: ["licence", "license", "dl", "driver"],
        ClassificationCategory.ACCIDENT_PHOTOS: ["photo", "accident", "damage", "car", "vehicle", "front", "rear", "left", "right", "jpg", "png", "jpeg"],
        ClassificationCategory.FIR_POLICY: ["fir", "police", "first information", "crime"],
    }

    target_keywords = indicators.get(target_category, [])
    matches = [kw for kw in target_keywords if kw in all_text]

    other_detected = None
    for cat, kws in indicators.items():
        if cat != target_category:
            hit_count = sum(1 for kw in kws if kw in all_text)
            if hit_count >= 2:
                other_detected = cat.value
                break

    is_valid = len(matches) > 0 or len(target_keywords) == 0 or not other_detected
    detected = category_val if is_valid else (other_detected or "unknown")

    for f in files:
        assessments.append(
            FileAssessment(
                filename=f.filename,
                status="VALID" if is_valid else "INVALID",
                detected_content=f"Detected content for {f.filename}",
                notes="Analyzed via offline heuristic fallback (Azure OpenAI not configured)",
            )
        )

    coverage = None
    if target_category == ClassificationCategory.ACCIDENT_PHOTOS:
        has_front = "front" in all_text or len(files) >= 1
        has_rear = "rear" in all_text or "back" in all_text or len(files) >= 2
        has_left = "left" in all_text or len(files) >= 3
        has_right = "right" in all_text or len(files) >= 4
        all_4 = has_front and has_rear and has_left and has_right
        missing = []
        if not has_front:
            missing.append("front_view")
        if not has_rear:
            missing.append("rear_view")
        if not has_left:
            missing.append("left_side_view")
        if not has_right:
            missing.append("right_side_view")

        coverage = AccidentPhotoCoverage(
            front_view=has_front,
            rear_view=has_rear,
            left_side_view=has_left,
            right_side_view=has_right,
            all_4_sides_present=all_4,
            missing_views=missing,
        )

    error_msg = None if is_valid else f"Uploaded document is not a valid {category_val}. Detected as {detected}."

    return ClassificationResponse(
        is_valid=is_valid,
        category_type=category_val,
        detected_type=detected,
        confidence=0.85 if is_valid else 0.40,
        description=f"Offline evaluation for requested category '{category_val}'. "
        + ("Document matches expected type." if is_valid else f"Invalid document. Expected {category_val} but found {detected}."),
        error=error_msg,
        file_assessments=assessments,
        accident_photo_coverage=coverage,
    )


async def classify_documents(
    category_type: str | ClassificationCategory, files: list[UploadedDoc]
) -> ClassificationResponse:
    """Classify uploaded document files using Azure OpenAI model."""
    if isinstance(category_type, str):
        target_category = ClassificationCategory.normalize(category_type)
    else:
        target_category = category_type

    if not files:
        return ClassificationResponse(
            is_valid=False,
            category_type=target_category.value,
            detected_type="none",
            confidence=0.0,
            description="No files were provided for classification.",
            error="No files uploaded. Please upload at least one file.",
        )

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not (settings.azure_openai_endpoint and api_key and settings.azure_openai_deployment):
        logger.warning("Azure OpenAI is not configured. Falling back to offline evaluation.")
        return _mock_classification_fallback(target_category, files)

    try:
        client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=api_key,
            api_version=settings.azure_openai_api_version,
        )

        prompt = f"""
You are an expert document and vehicle damage classifier for a motor insurance system.
The user wants to classify uploaded file(s) for the requested category: '{target_category.value}'.

Supported categories:
1. survey_report (Survey Report Motor Insurance)
2. repair_invoice (Repair Invoice / Bill)
3. repair_estimate (Repair Estimate Details / Garage Estimate)
4. insurance_policy (Motor Insurance Policy Document)
5. claim_form (Motor Insurance Claim Form)
6. registration_certificate (RC / Registration Certificate)
7. driving_licence (Driver Licence / Driving License)
8. accident_photos (Car Pics 4 Sides: Vehicle accident photos covering Front, Rear, Left, Right)

YOUR TASKS:
1. Inspect the uploaded image(s) / document(s) carefully.
2. Identify the actual document type or image content provided in the file(s).
3. Evaluate if the uploaded content IS VALID for the requested category '{target_category.value}'.
4. For 'accident_photos' specifically:
   - Check whether the images clearly show vehicle damage/accident.
   - Verify if photos cover all 4 sides of the vehicle: front_view, rear_view, left_side_view, right_side_view.
   - Set `all_4_sides_present` to true if all 4 angles are captured, otherwise false and list `missing_views`.
5. IF INVALID: Set `is_valid` to false, explain what was detected, and write a clear, helpful error message in `error` describing why it is invalid.
6. IF VALID: Set `is_valid` to true, `error` to null, and describe the document in `description`.

Return ONLY valid JSON matching this schema:
{{
  "is_valid": boolean,
  "category_type": "{target_category.value}",
  "detected_type": "string (e.g. survey_report, repair_invoice, registration_certificate, etc.)",
  "confidence": float (between 0.0 and 1.0),
  "description": "string (detailed summary of the document and findings)",
  "error": "string or null (error message with reason if is_valid is false)",
  "file_assessments": [
     {{
       "filename": "string",
       "status": "VALID" | "INVALID" | "NEEDS_REVIEW",
       "detected_content": "string",
       "notes": "string"
     }}
  ],
  "accident_photo_coverage": {{
     "front_view": boolean,
     "rear_view": boolean,
     "left_side_view": boolean,
     "right_side_view": boolean,
     "all_4_sides_present": boolean,
     "missing_views": ["front_view", "rear_view", "left_side_view", "right_side_view"]
  }}
}}
Note: `accident_photo_coverage` should be included if requested category is `accident_photos`, otherwise set it to null.
"""
        content_parts: list[dict] = [{"type": "text", "text": prompt}]

        for file in files:
            mime = _determine_mime_type(file.filename, file.content_type)
            if mime.startswith("image/"):
                b64_str = base64.b64encode(file.content).decode("ascii")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64_str}",
                        "detail": "low",
                    },
                })
            elif mime == "application/pdf":
                pdf_text = _extract_text_from_pdf(file.content)
                content_parts.append({
                    "type": "text",
                    "text": f"File '{file.filename}' (PDF text excerpt):\n{pdf_text[:8000] if pdf_text else '[PDF could not be OCR-read directly]'}",
                })
            else:
                try:
                    text_str = file.content.decode("utf-8", errors="ignore")
                    content_parts.append({
                        "type": "text",
                        "text": f"File '{file.filename}' (text):\n{text_str[:8000]}",
                    })
                except Exception:
                    content_parts.append({
                        "type": "text",
                        "text": f"File '{file.filename}' [binary file]",
                    })

        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": content_parts}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        response_text = response.choices[0].message.content or "{}"
        data = json.loads(response_text)

        is_valid = bool(data.get("is_valid", False))
        detected_type = data.get("detected_type", "unknown")
        confidence = float(data.get("confidence", 0.9 if is_valid else 0.3))
        description = data.get("description", "Azure OpenAI document classification performed.")
        error_text = data.get("error")

        if not is_valid and not error_text:
            error_text = f"Uploaded document is not a valid {target_category.value}. Detected type: '{detected_type}'."

        file_assessments = [
            FileAssessment(
                filename=item.get("filename", files[idx].filename if idx < len(files) else "file"),
                status=item.get("status", "VALID" if is_valid else "INVALID"),
                detected_content=item.get("detected_content", detected_type),
                notes=item.get("notes", ""),
            )
            for idx, item in enumerate(data.get("file_assessments", []))
        ]

        if not file_assessments:
            file_assessments = [
                FileAssessment(
                    filename=f.filename,
                    status="VALID" if is_valid else "INVALID",
                    detected_content=detected_type,
                    notes=description,
                )
                for f in files
            ]

        cov_data = data.get("accident_photo_coverage")
        coverage = None
        if cov_data and isinstance(cov_data, dict):
            coverage = AccidentPhotoCoverage(
                front_view=bool(cov_data.get("front_view", False)),
                rear_view=bool(cov_data.get("rear_view", False)),
                left_side_view=bool(cov_data.get("left_side_view", False)),
                right_side_view=bool(cov_data.get("right_side_view", False)),
                all_4_sides_present=bool(cov_data.get("all_4_sides_present", False)),
                missing_views=cov_data.get("missing_views", []),
            )

        return ClassificationResponse(
            is_valid=is_valid,
            category_type=target_category.value,
            detected_type=detected_type,
            confidence=round(confidence, 2),
            description=description,
            error=error_text,
            file_assessments=file_assessments,
            accident_photo_coverage=coverage,
        )

    except Exception as exc:
        logger.exception("Azure OpenAI classification failed: %s", exc)
        return ClassificationResponse(
            is_valid=False,
            category_type=target_category.value,
            detected_type="error",
            confidence=0.0,
            description="Azure OpenAI classification failed.",
            error=f"Classification error: {str(exc)}",
        )


# Backward compatibility alias
classify_documents_with_gemini = classify_documents
