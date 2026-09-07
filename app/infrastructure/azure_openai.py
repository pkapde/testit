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
    """Return whether Azure OpenAI is configured for server-side use."""
    return bool(settings.azure_openai_endpoint and settings.azure_openai_deployment)


def configured_model_name() -> str:
    """Return the configured Azure OpenAI deployment name."""
    if not settings.azure_openai_deployment:
        raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not configured")
    return settings.azure_openai_deployment


def _openai_compatible_base_url(endpoint: str) -> str:
    """Return the Azure OpenAI v1-compatible base URL used by the working client.

    Azure accepts the OpenAI SDK's standard client against its ``/openai/v1/``
    endpoint.  Keeping this normalisation in one place prevents a deployment
    endpoint from being accidentally appended twice when configuration already
    includes the path.
    """
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/openai/v1"):
        return f"{normalized}/"
    return f"{normalized}/openai/v1/"


def create_chat_client():
    """Create the working Azure OpenAI v1-compatible client.

    This intentionally follows the previously working integration format:
    ``OpenAI(base_url=<azure-endpoint>/openai/v1/, api_key=<key>)``.  All
    agents share this factory so classification, extraction, review, and
    assessment cannot drift to incompatible SDK URL formats.
    """

    from openai import OpenAI
    from app.infrastructure.secrets import get_secret

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not api_key:
        raise RuntimeError("Azure OpenAI API key is not configured")
    if not settings.azure_openai_endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
    return OpenAI(
        base_url=_openai_compatible_base_url(settings.azure_openai_endpoint),
        api_key=api_key,
    )


def _log_provider_failure(operation: str, error: Exception) -> None:
    """Log diagnosable provider failures without logging secrets or claim content."""
    logger.warning("LLM provider %s failed: %s: %s", operation, type(error).__name__, str(error))


def classify_document(*, file_name: str, content: bytes, extracted_text: str) -> tuple[DocumentType, float, list[str]] | None:
    """Classify an ambiguous document with Azure OpenAI and return safe structured output.

    The original file stays in the request boundary. Only this short-lived call receives
    the image itself (for image formats) or a capped OCR/text excerpt (for PDFs/text).
    """
    if not is_configured():
        return None


    try:
        client = create_chat_client()
    except RuntimeError as exc:
        _log_provider_failure("document classification", exc)
        return None
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
            model=configured_model_name(),
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

    prompt = (
        "Extract motor-insurance fields from the supplied OCR/text. Return JSON only with a `fields` object. "
        f"The document is classified as `{document_type.value}` and the only permitted keys are {list(allowed_fields)}. "
        "Include a key only when its value is explicitly present in the text. Do not infer, calculate, or fabricate values. "
        "Use the source spelling for names and narrative text. OCR/text follows:\n"
        f"{extracted_text[:12000]}"
    )
    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            model=configured_model_name(),
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
    prompt = (
        "You are a motor-insurance cross-document review assistant. Review only the supplied extracted fields. "
        "Return JSON only: {\"findings\": [{\"field\": string, \"assessment\": \"CONSISTENT\"|\"INCONSISTENT\"|\"NEEDS_REVIEW\", \"confidence\": number 0..1, \"rationale\": string}]}. "
        "Assess semantic differences such as abbreviated names, conflicting accident descriptions, or a claimant/owner relationship that needs review. "
        "Never invent information, make a coverage decision, or recommend approval/rejection. Do not report exact registration, date, or amount differences; those are deterministic checks. "
        f"Extracted fields: {json.dumps(extracted_fields, ensure_ascii=False)}"
    )
    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            model=configured_model_name(),
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
    prompt = (
        "You are an insurance fraud-investigation assistant. Review only the supplied structured extracted fields "
        "and deterministic validation signals. Return JSON only: {\"hypotheses\": [{\"indicator\": string, \"confidence\": number 0..1, \"rationale\": string, \"recommended_review\": string}]}. "
        "A hypothesis is not a fraud conclusion. Include an item only for a concrete inconsistency, anomaly, or evidence gap. "
        "Never accuse a claimant, recommend rejection, calculate a payout, or invent facts. Keep each rationale and recommendation under 500 characters. "
        f"Extracted fields: {json.dumps(extracted_fields, ensure_ascii=False)}\n"
        f"Deterministic signals: {json.dumps(deterministic_signals, ensure_ascii=False)}"
    )
    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            model=configured_model_name(),
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
    except Exception as exc:
        _log_provider_failure("fraud investigation", exc)
        return None


def explain_coverage(*, facts: dict[str, str], clauses: list[dict[str, str]]) -> str | None:
    """Return an advisory coverage explanation grounded only in retrieved clauses."""
    if not is_configured() or not clauses:
        return None
    prompt = ("You are an insurance coverage assistant. Use only the provided claim facts and clause excerpts. "
              "Return JSON: {\"explanation\": string}. Explain which cited clause references require human assessment. "
              "Do not decide approval, rejection, liability, fraud, or payout; do not invent terms. "
              f"Facts: {json.dumps(facts)} Clauses: {json.dumps(clauses)}")
    try:
        client = create_chat_client()
        response = client.chat.completions.create(model=configured_model_name(), messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"})
        explanation = str(json.loads(response.choices[0].message.content or "{}").get("explanation", "")).strip()[:2000]
        return explanation or None
    except Exception as exc:
        _log_provider_failure("coverage explanation", exc)
        return None


def answer_policy_enquiry(*, query: str, clauses: list[dict[str, str]]) -> str | None:
    """Answer a customer policy question using only retrieved approved wording."""
    if not is_configured() or not clauses:
        return None
    prompt = (
        "You are a motor-insurance policy information assistant. Answer only from the supplied approved policy excerpts. "
        "Return JSON: {\"answer\": string}. State clearly that this is informational and a Claims Adjuster makes coverage, liability, and payout decisions. "
        "Do not invent clauses, infer a policyholder's eligibility, or decide a claim. "
        f"Question: {query} Approved excerpts: {json.dumps(clauses)}"
    )
    try:
        client = create_chat_client()
        response = client.chat.completions.create(
            model=configured_model_name(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        answer = str(json.loads(response.choices[0].message.content or "{}").get("answer", "")).strip()[:2000]
        return answer or None
    except Exception as exc:
        _log_provider_failure("policy enquiry", exc)
        return None


def generate_claim_assessment(*, summary: str, evidence: list[str], checklist: list[str]) -> dict[str, object] | None:
    """Draft a factual review summary and checklist; never a decision or payout."""
    if not is_configured():
        return None
    prompt = ("You draft an insurance claims-officer review brief. Return JSON only: {\"case_summary\": string, \"reviewer_checklist\": [string]}. "
              "Use only the supplied data. Do not approve/reject a claim, determine fraud, interpret new policy terms, or recommend a payout. "
              f"Summary: {summary} Evidence: {json.dumps(evidence)} Checklist: {json.dumps(checklist)}")
    try:
        client = create_chat_client()
        response = client.chat.completions.create(model=configured_model_name(), messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"})
        payload = json.loads(response.choices[0].message.content or "{}")
        text = str(payload.get("case_summary", "")).strip()[:2000]
        items = [str(item).strip()[:500] for item in payload.get("reviewer_checklist", []) if str(item).strip()][:10]
        return {"case_summary": text, "reviewer_checklist": items} if text else None
    except Exception as exc:
        _log_provider_failure("claim assessment", exc)
        return None


def explain_settlement_recommendation(*, preliminary_amount: str, basis: list[str]) -> str | None:
    """Draft a reviewer explanation; it cannot create or change the amount."""
    if not is_configured():
        return None
    prompt = ("You explain a preliminary motor-claim settlement figure to a claims officer. Return JSON: {\"explanation\": string}. "
              "Use only the fixed amount and listed basis. State that this is not an approval and needs human confirmation. "
              "Do not change the amount, infer deductibles, approve/reject, or introduce policy terms. "
              f"Amount: INR {preliminary_amount}. Basis: {json.dumps(basis)}")
    try:
        client = create_chat_client()
        response = client.chat.completions.create(model=configured_model_name(), messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"})
        text = str(json.loads(response.choices[0].message.content or "{}").get("explanation", "")).strip()[:1500]
        return text or None
    except Exception as exc:
        _log_provider_failure("settlement explanation", exc)
        return None
