"""Azure OpenAI tools used only when deterministic classification is insufficient."""
import base64
import json
import logging
from pathlib import Path

from app.core.config import settings
from app.schemas.documents import DocumentType

logger = logging.getLogger(__name__)

EXTRACTION_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.CLAIM_FORM: ("claim_number", "person_name", "vehicle_registration", "accident_date", "accident_details"),
    DocumentType.RC: ("person_name", "vehicle_registration", "chassis_number", "engine_number", "registration_date"),
    DocumentType.POLICY: ("person_name", "vehicle_registration", "policy_number", "policy_start_date", "policy_end_date", "insured_declared_value"),
    DocumentType.DRIVING_LICENCE: ("person_name", "licence_number", "licence_valid_till", "vehicle_class_authorised"),
    DocumentType.FIR: ("person_name", "vehicle_registration", "fir_number", "police_station", "accident_date"),
    DocumentType.GARAGE_ESTIMATE: ("vehicle_registration", "estimate_number", "garage_name", "parts_total", "labour_charges", "estimate_total"),
    DocumentType.REPAIR_INVOICE: ("vehicle_registration", "invoice_number", "garage_name", "invoice_total"),
    DocumentType.ACCIDENT_PHOTOS: ("vehicle_registration",),
    DocumentType.UNKNOWN: (),
}


def is_configured() -> bool:
    """Return whether a deployment and endpoint are available for AI classification."""
    return bool(settings.azure_openai_endpoint and settings.azure_openai_deployment)


def _log_provider_failure(operation: str, error: Exception) -> None:
    """Log diagnosable provider failures without logging secrets or claim content."""
    logger.warning("Azure OpenAI %s failed: %s: %s", operation, type(error).__name__, str(error))


def classify_document(*, file_name: str, content: bytes, extracted_text: str) -> tuple[DocumentType, float, list[str]] | None:
    """Classify an ambiguous document with Azure OpenAI and return safe structured output.

    The original file stays in the request boundary. Only this short-lived call receives
    the image itself (for image formats) or a capped OCR/text excerpt (for PDFs/text).
    """
    if not is_configured():
        return None

    from openai import AzureOpenAI
    from app.infrastructure.secrets import get_secret

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not api_key:
        return None
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=api_key,
        api_version=settings.azure_openai_api_version,
    )
    allowed_types = [document_type.value for document_type in DocumentType]
    prompt = (
        "You classify motor-insurance claim uploads. Return JSON only with keys "
        "document_type, confidence, evidence. document_type must be one of "
        f"{allowed_types}. confidence must be a number from 0 to 1. evidence must be a short list of observed clues. "
        "Use unknown when the evidence is insufficient. Do not infer facts that are not visible. "
        f"File name: {file_name}. Extracted text/OCR (may be empty): {extracted_text[:6000]}"
    )
    extension = Path(file_name).suffix.lower()
    content_part: list[dict] = [{"type": "text", "text": prompt}]
    if extension in {".jpg", ".jpeg", ".png"}:
        mime_type = "image/png" if extension == ".png" else "image/jpeg"
        data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        content_part.append({"type": "image_url", "image_url": {"url": data_url, "detail": "low"}})
    try:
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": content_part}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        detected = DocumentType(payload.get("document_type", DocumentType.UNKNOWN.value))
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
        evidence = [str(item) for item in payload.get("evidence", [])][:5]
        return detected, round(confidence, 2), evidence
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        _log_provider_failure("document classification", exc)
        return None
    except Exception as exc:
        # Classification is advisory. A provider failure must never mark a claim valid.
        _log_provider_failure("document classification", exc)
        return None


def extract_document_fields(*, file_name: str, document_type: DocumentType, extracted_text: str) -> dict[str, str] | None:
    """Use Azure OpenAI to extract only the schema fields allowed for one document type.

    This is an agent tool, not a source of truth: the calling extraction service
    normalises and validates every returned value before it is used downstream.
    """
    if not is_configured() or not extracted_text.strip():
        return None
    allowed_fields = EXTRACTION_FIELDS[document_type]
    if not allowed_fields:
        return {}

    from openai import AzureOpenAI
    from app.infrastructure.secrets import get_secret

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not api_key:
        return None
    prompt = (
        "Extract motor-insurance fields from the supplied OCR/text. Return JSON only with a `fields` object. "
        f"The document is classified as `{document_type.value}` and the only permitted keys are {list(allowed_fields)}. "
        "Include a key only when its value is explicitly present in the text. Do not infer, calculate, or fabricate values. "
        "Use the source spelling for names and narrative text. OCR/text follows:\n"
        f"{extracted_text[:12000]}"
    )
    try:
        client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=api_key,
            api_version=settings.azure_openai_api_version,
        )
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, dict):
            logger.warning("Azure OpenAI structured extraction returned no fields object")
            return None
        return {
            key: str(value).strip()[:500]
            for key, value in raw_fields.items()
            if key in allowed_fields and value is not None and str(value).strip().lower() not in {"", "n/a", "na", "unknown", "null"}
        }
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        _log_provider_failure("structured extraction", exc)
        return None
    except Exception as exc:
        # An advisory model failure never blocks deterministic processing.
        _log_provider_failure("structured extraction", exc)
        return None


def assess_cross_document_consistency(extracted_fields: dict[str, dict[str, str]]) -> list[dict] | None:
    """Ask the LLM for semantic consistency findings based on extracted values only.

    Exact identifiers, dates, and money are still checked deterministically by the
    calling service. The model may only recommend a human-review finding.
    """
    if not is_configured() or not extracted_fields:
        return None
    from openai import AzureOpenAI
    from app.infrastructure.secrets import get_secret

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not api_key:
        return None
    prompt = (
        "You are a motor-insurance cross-document review assistant. Review only the supplied extracted fields. "
        "Return JSON only: {\"findings\": [{\"field\": string, \"assessment\": \"CONSISTENT\"|\"INCONSISTENT\"|\"NEEDS_REVIEW\", \"confidence\": number 0..1, \"rationale\": string}]}. "
        "Assess semantic differences such as abbreviated names, conflicting accident descriptions, or a claimant/owner relationship that needs review. "
        "Never invent information, make a coverage decision, or recommend approval/rejection. Do not report exact registration, date, or amount differences; those are deterministic checks. "
        f"Extracted fields: {json.dumps(extracted_fields, ensure_ascii=False)}"
    )
    try:
        client = AzureOpenAI(azure_endpoint=settings.azure_openai_endpoint, api_key=api_key, api_version=settings.azure_openai_api_version)
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        findings = payload.get("findings")
        if not isinstance(findings, list):
            logger.warning("Azure OpenAI cross-document review returned no findings list")
            return None
        safe_findings = []
        for finding in findings[:10]:
            if not isinstance(finding, dict):
                continue
            assessment = str(finding.get("assessment", "")).upper()
            field = str(finding.get("field", "")).strip()[:100]
            rationale = str(finding.get("rationale", "")).strip()[:1000]
            try:
                confidence = max(0.0, min(1.0, float(finding.get("confidence", 0.0))))
            except (TypeError, ValueError):
                continue
            if assessment in {"CONSISTENT", "INCONSISTENT", "NEEDS_REVIEW"} and field and rationale:
                safe_findings.append({"field": field, "assessment": assessment, "confidence": confidence, "rationale": rationale})
        return safe_findings
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        _log_provider_failure("cross-document review", exc)
        return None
    except Exception as exc:
        _log_provider_failure("cross-document review", exc)
        return None


def assess_fraud_hypotheses(extracted_fields: dict[str, dict[str, str]], deterministic_signals: list[dict[str, str]]) -> list[dict] | None:
    """Generate advisory fraud-review hypotheses from sanitized claim facts.

    This tool cannot make a fraud determination. Callers treat every returned
    hypothesis as MEDIUM-risk human-review evidence only; deterministic rules
    remain the sole source of HIGH-risk routing.
    """
    if not is_configured() or not extracted_fields:
        return None
    from openai import AzureOpenAI
    from app.infrastructure.secrets import get_secret

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not api_key:
        return None
    prompt = (
        "You are an insurance fraud-investigation assistant. Review only the supplied structured extracted fields "
        "and deterministic validation signals. Return JSON only: {\"hypotheses\": [{\"indicator\": string, \"confidence\": number 0..1, \"rationale\": string, \"recommended_review\": string}]}. "
        "A hypothesis is not a fraud conclusion. Include an item only for a concrete inconsistency, anomaly, or evidence gap. "
        "Never accuse a claimant, recommend rejection, calculate a payout, or invent facts. Keep each rationale and recommendation under 500 characters. "
        f"Extracted fields: {json.dumps(extracted_fields, ensure_ascii=False)}\n"
        f"Deterministic signals: {json.dumps(deterministic_signals, ensure_ascii=False)}"
    )
    try:
        client = AzureOpenAI(azure_endpoint=settings.azure_openai_endpoint, api_key=api_key, api_version=settings.azure_openai_api_version)
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        hypotheses = payload.get("hypotheses")
        if not isinstance(hypotheses, list):
            logger.warning("Azure OpenAI fraud investigation returned no hypotheses list")
            return None
        safe_hypotheses = []
        for hypothesis in hypotheses[:5]:
            if not isinstance(hypothesis, dict):
                continue
            indicator = str(hypothesis.get("indicator", "")).strip()[:150]
            rationale = str(hypothesis.get("rationale", "")).strip()[:500]
            recommended_review = str(hypothesis.get("recommended_review", "")).strip()[:500]
            try:
                confidence = max(0.0, min(1.0, float(hypothesis.get("confidence", 0.0))))
            except (TypeError, ValueError):
                continue
            if indicator and rationale and recommended_review:
                safe_hypotheses.append({"indicator": indicator, "confidence": confidence, "rationale": rationale, "recommended_review": recommended_review})
        return safe_hypotheses
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        _log_provider_failure("fraud investigation", exc)
        return None
    except Exception as exc:
        _log_provider_failure("fraud investigation", exc)
        return None
