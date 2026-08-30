"""Structured extraction and explainable cross-document checks for motor claims."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from app.core.config import settings
from app.schemas.documents import AgenticFinding, ClaimTriageResult, CrossDocumentIssue, DocumentType, FieldValidationIssue, FileStatus, TriageQueue
from app.services.validator import IncomingFile, _extract_text, validate_claim

VEHICLE_REGISTRATION = re.compile(r"\b([A-Z]{2})\s?(\d{1,2})\s?([A-Z]{1,3})\s?(\d{4})\b", re.IGNORECASE)
DATE_TOKEN = r"\d{1,2}(?:[/-][A-Za-z0-9]{2,10}|\s+[A-Za-z]{3,9}\s+\d{4})|\d{4}-\d{1,2}-\d{1,2}"
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d")
CORE_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.CLAIM_FORM: ("vehicle_registration", "accident_date"),
    DocumentType.RC: ("vehicle_registration", "chassis_number", "engine_number"),
    DocumentType.POLICY: ("vehicle_registration", "policy_number", "policy_start_date", "policy_end_date"),
    DocumentType.DRIVING_LICENCE: ("licence_number", "licence_valid_till"),
    DocumentType.GARAGE_ESTIMATE: ("vehicle_registration", "estimate_total"),
}


def _normalise_registration(match: re.Match) -> str:
    return "".join(match.groups()).upper()


def _normalised_name(value: str) -> str:
    value = re.sub(r"\s*-\s*SYNTHETIC TEST DATA\b", "", value, flags=re.IGNORECASE)
    return " ".join(value.split()).upper()


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _label_value(text: str, labels: tuple[str, ...]) -> str | None:
    """Read a value from either `Label: value` or adjacent PDF table rows."""
    lines = _lines(text)
    label_pattern = "|".join(re.escape(label) for label in labels)
    matcher = re.compile(rf"^(?:{label_pattern})\s*[:#-]?\s*(.*)$", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = matcher.match(line)
        if not match:
            continue
        if match.group(1).strip():
            return match.group(1).strip()
        if index + 1 < len(lines):
            return lines[index + 1]
    inline = re.sub(r"\s+", " ", text)
    match = re.search(rf"(?:{label_pattern})\s*[:#-]?\s*([^\n]+)", inline, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _normalise_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(DATE_TOKEN, value)
    if not match:
        return None
    candidate = " ".join(match.group(0).split())
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(candidate, date_format).date()
        except ValueError:
            pass
    return None


def _date_string(value: str | None) -> str | None:
    parsed = _normalise_date(value)
    return parsed.isoformat() if parsed else None


def _amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"(?:INR|Rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)", value, re.IGNORECASE)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _money_string(value: str | None) -> str | None:
    amount = _amount(value)
    return f"{amount:.2f}" if amount is not None else None


def _put(fields: dict[str, str], key: str, value: str | None, transform=lambda value: value) -> None:
    if value:
        transformed = transform(value)
        if transformed:
            fields[key] = transformed


def _normalise_llm_field(key: str, value: str) -> str | None:
    """Apply deterministic validation to a value returned by the LLM extraction tool."""
    if key == "vehicle_registration":
        match = VEHICLE_REGISTRATION.search(value)
        return _normalise_registration(match) if match else None
    if key in {"accident_date", "policy_start_date", "policy_end_date", "registration_date", "licence_valid_till"}:
        return _date_string(value)
    if key in {"insured_declared_value", "parts_total", "labour_charges", "estimate_total", "invoice_total"}:
        return _money_string(value)
    if key == "person_name":
        return _normalised_name(value)
    if key in {"claim_number", "policy_number", "licence_number", "chassis_number", "engine_number", "fir_number", "estimate_number", "invoice_number", "vehicle_class_authorised", "garage_name"}:
        return value.upper()
    return value


def _augment_with_llm(fields: dict[str, str], item: IncomingFile, document_type: DocumentType, text: str) -> str:
    """Fill deterministic gaps with Azure OpenAI and return the transparent extraction method."""
    from app.infrastructure.azure_openai import extract_document_fields, is_configured

    if not is_configured():
        return "DETERMINISTIC"
    ai_fields = extract_document_fields(file_name=item.name, document_type=document_type, extracted_text=text)
    if ai_fields is None:
        return "DETERMINISTIC"
    added = False
    for key, raw_value in ai_fields.items():
        if key in fields:
            continue
        normalised = _normalise_llm_field(key, raw_value)
        if normalised:
            fields[key] = normalised
            added = True
    return "DETERMINISTIC_PLUS_AZURE_OPENAI" if added else "DETERMINISTIC_VERIFIED_BY_AZURE_OPENAI"


def extract_fields(text: str, document_type: DocumentType) -> dict[str, str]:
    """Extract core Phase 2 fields by document type; extraction never approves a claim."""
    fields: dict[str, str] = {}
    registration = VEHICLE_REGISTRATION.search(text)
    if registration:
        fields["vehicle_registration"] = _normalise_registration(registration)
    _put(fields, "person_name", _label_value(text, ("owner name", "policyholder", "insured name", "claimant", "holder name", "complainant")), _normalised_name)

    if document_type == DocumentType.CLAIM_FORM:
        _put(fields, "claim_number", _label_value(text, ("claim number", "claim no")), lambda value: value.upper())
        _put(fields, "accident_date", _label_value(text, ("date of loss", "accident date", "date of occurrence")), _date_string)
        _put(fields, "accident_details", _label_value(text, ("accident details", "nature of loss")))
    elif document_type == DocumentType.RC:
        _put(fields, "chassis_number", _label_value(text, ("chassis number", "chassis no")), lambda value: value.upper())
        _put(fields, "engine_number", _label_value(text, ("engine number", "engine no")), lambda value: value.upper())
        _put(fields, "registration_date", _label_value(text, ("date of registration",)), _date_string)
    elif document_type == DocumentType.POLICY:
        _put(fields, "policy_number", _label_value(text, ("policy number", "policy no")), lambda value: value.upper())
        period = _label_value(text, ("period of insurance", "policy period"))
        if period:
            dates = re.findall(DATE_TOKEN, period)
            if len(dates) >= 2:
                _put(fields, "policy_start_date", dates[0], _date_string)
                _put(fields, "policy_end_date", dates[1], _date_string)
        _put(fields, "insured_declared_value", _label_value(text, ("insured declared value", "idv")), _money_string)
    elif document_type == DocumentType.DRIVING_LICENCE:
        _put(fields, "licence_number", _label_value(text, ("licence number", "license number", "licence no", "license no", "dl no")), lambda value: value.upper())
        _put(fields, "licence_valid_till", _label_value(text, ("valid till", "valid upto", "valid up to")), _date_string)
        _put(fields, "vehicle_class_authorised", _label_value(text, ("vehicle classes authorized", "vehicle class", "class of vehicle")), lambda value: value.upper())
    elif document_type == DocumentType.FIR:
        _put(fields, "fir_number", _label_value(text, ("fir no", "fir number", "crime no")), lambda value: value.upper())
        _put(fields, "police_station", _label_value(text, ("police station",)))
        _put(fields, "accident_date", _label_value(text, ("date and time of occurrence", "date of occurrence", "accident date")), _date_string)
    elif document_type == DocumentType.GARAGE_ESTIMATE:
        _put(fields, "estimate_number", _label_value(text, ("estimate no", "estimate number")), lambda value: value.upper())
        _put(fields, "garage_name", _label_value(text, ("garage name", "workshop name")), lambda value: value.upper())
        _put(fields, "parts_total", _label_value(text, ("parts total",)), _money_string)
        _put(fields, "labour_charges", _label_value(text, ("labour charges", "labor charges")), _money_string)
        _put(fields, "estimate_total", _label_value(text, ("estimated cost", "estimate amount", "total estimate")), _money_string)
    elif document_type == DocumentType.REPAIR_INVOICE:
        _put(fields, "invoice_number", _label_value(text, ("invoice number", "invoice no")), lambda value: value.upper())
        _put(fields, "garage_name", _label_value(text, ("garage name", "workshop name")), lambda value: value.upper())
        _put(fields, "invoice_total", _label_value(text, ("amount payable", "bill amount", "total invoice value")), _money_string)
    return fields


def _inconsistent_field(extracted: dict[str, dict[str, str]], field: str, severity: str, message: str) -> CrossDocumentIssue | None:
    values = {name: fields[field] for name, fields in extracted.items() if field in fields}
    if len(set(values.values())) > 1:
        return CrossDocumentIssue(field=field, values_by_document=values, severity=severity, message=message)
    return None


def _policy_and_licence_issues(extracted: dict[str, dict[str, str]]) -> list[CrossDocumentIssue]:
    issues: list[CrossDocumentIssue] = []
    accident_dates = [date.fromisoformat(fields["accident_date"]) for fields in extracted.values() if fields.get("accident_date")]
    policy_starts = [date.fromisoformat(fields["policy_start_date"]) for fields in extracted.values() if fields.get("policy_start_date")]
    policy_ends = [date.fromisoformat(fields["policy_end_date"]) for fields in extracted.values() if fields.get("policy_end_date")]
    licence_ends = [date.fromisoformat(fields["licence_valid_till"]) for fields in extracted.values() if fields.get("licence_valid_till")]
    if accident_dates and policy_starts and policy_ends:
        accident_date, start, end = accident_dates[0], policy_starts[0], policy_ends[0]
        if not start <= accident_date <= end:
            issues.append(CrossDocumentIssue(field="policy_coverage_period", values_by_document={"accident_date": accident_date.isoformat(), "policy_start_date": start.isoformat(), "policy_end_date": end.isoformat()}, severity="HIGH", message="Accident date falls outside the submitted policy period."))
    if accident_dates and licence_ends and accident_dates[0] > licence_ends[0]:
        issues.append(CrossDocumentIssue(field="licence_validity", values_by_document={"accident_date": accident_dates[0].isoformat(), "licence_valid_till": licence_ends[0].isoformat()}, severity="HIGH", message="Driving licence was expired on the reported accident date."))
    return issues


def _financial_variance_issue(extracted: dict[str, dict[str, str]]) -> CrossDocumentIssue | None:
    estimate = next((Decimal(fields["estimate_total"]) for fields in extracted.values() if fields.get("estimate_total")), None)
    invoice = next((Decimal(fields["invoice_total"]) for fields in extracted.values() if fields.get("invoice_total")), None)
    if estimate is None or invoice is None or estimate == 0:
        return None
    variance = abs(invoice - estimate) / estimate
    if variance > Decimal(str(settings.estimate_invoice_variance_threshold)):
        return CrossDocumentIssue(field="estimate_invoice_variance", values_by_document={"estimate_total": f"{estimate:.2f}", "invoice_total": f"{invoice:.2f}", "variance_percent": f"{variance * 100:.2f}"}, severity="MEDIUM", message="Repair invoice differs from the garage estimate beyond the configured review threshold.")
    return None


def _agentic_cross_document_findings(extracted: dict[str, dict[str, str]]) -> list[AgenticFinding]:
    """Return LLM semantic findings only when Azure OpenAI is configured."""
    from app.infrastructure.azure_openai import assess_cross_document_consistency

    findings = assess_cross_document_consistency(extracted)
    return [AgenticFinding(**finding) for finding in findings or []]


def _field_validation_issues(validation, extracted: dict[str, dict[str, str]]) -> list[FieldValidationIssue]:
    """Ensure a classified required document has the minimum usable claim fields."""
    issues: list[FieldValidationIssue] = []
    for outcome in validation.files:
        if outcome.status != FileStatus.VALID:
            continue
        fields = extracted.get(outcome.file_name, {})
        for field in CORE_FIELDS.get(outcome.detected_document, ()):
            if field not in fields:
                issues.append(FieldValidationIssue(file_name=outcome.file_name, field=field, severity="HIGH", message=f"Required {field.replace('_', ' ')} could not be extracted from this {outcome.detected_document.value} document."))
        if outcome.detected_document == DocumentType.POLICY and fields.get("policy_start_date") and fields.get("policy_end_date"):
            if date.fromisoformat(fields["policy_start_date"]) > date.fromisoformat(fields["policy_end_date"]):
                issues.append(FieldValidationIssue(file_name=outcome.file_name, field="policy_period", severity="HIGH", message="Policy start date is after policy end date."))
        if outcome.detected_document == DocumentType.GARAGE_ESTIMATE and fields.get("estimate_total"):
            if Decimal(fields["estimate_total"]) <= 0:
                issues.append(FieldValidationIssue(file_name=outcome.file_name, field="estimate_total", severity="HIGH", message="Garage estimate total must be greater than zero."))
    return issues


def build_triage_result(validation, items: list[IncomingFile]) -> ClaimTriageResult:
    extracted: dict[str, dict[str, str]] = {}
    extraction_method_by_document: dict[str, str] = {}
    for item, outcome in zip(items, validation.files):
        if outcome.status != FileStatus.VALID:
            continue
        text, error = _extract_text(item)
        if not error and text:
            fields = extract_fields(text, outcome.detected_document)
            extraction_method = _augment_with_llm(fields, item, outcome.detected_document, text)
            extracted[outcome.file_name] = fields
            extraction_method_by_document[outcome.file_name] = extraction_method

    issues: list[CrossDocumentIssue] = []
    field_issues = _field_validation_issues(validation, extracted)
    for field, severity, message in [
        ("vehicle_registration", "HIGH", "Vehicle registration differs across submitted documents."),
        ("person_name", "MEDIUM", "Customer/owner name differs across submitted documents."),
        ("accident_date", "HIGH", "Accident date differs across submitted documents."),
        ("garage_name", "MEDIUM", "Garage name differs between estimate and invoice."),
    ]:
        issue = _inconsistent_field(extracted, field, severity, message)
        if issue:
            issues.append(issue)
    issues.extend(_policy_and_licence_issues(extracted))
    variance_issue = _financial_variance_issue(extracted)
    if variance_issue:
        issues.append(variance_issue)
    agentic_findings = _agentic_cross_document_findings(extracted)
    agentic_review_required = any(finding.assessment in {"INCONSISTENT", "NEEDS_REVIEW"} for finding in agentic_findings)

    if validation.overall_status != "COMPLETE" or field_issues:
        queue, reason = TriageQueue.DOCUMENT_VERIFICATION, "Missing, unreadable, duplicate, ambiguous, or wrong documents require document verification."
    elif issues or agentic_review_required:
        queue, reason = TriageQueue.CLAIMS_OFFICER, "Cross-document inconsistency requires claims-officer review."
    else:
        queue, reason = TriageQueue.READY_FOR_EXTRACTION, "Document package is complete and contains no detected cross-document inconsistency."
    if field_issues and validation.overall_status == "COMPLETE":
        reason = "A required document is missing a usable core field and requires document verification."
    return ClaimTriageResult(validation=validation, extracted_fields=extracted, extraction_method_by_document=extraction_method_by_document, field_validation_issues=field_issues, cross_document_issues=issues, agentic_findings=agentic_findings, routing_queue=queue, routing_reason=reason)


def triage_claim(claim_id: str, items: list[IncomingFile]) -> ClaimTriageResult:
    return build_triage_result(validate_claim(claim_id, items), items)
