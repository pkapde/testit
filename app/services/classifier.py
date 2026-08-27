from collections import Counter
import re
from app.schemas.documents import DocumentType

KEYWORDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.CLAIM_FORM: ("claim form", "claimant", "date of loss", "accident details", "claim number", "nature of loss"),
    DocumentType.RC: ("registration certificate", "certificate of registration", "registration no", "registration number", "regn no", "vehicle class", "chassis no", "chassis number", "engine no", "engine number", "maker's name", "date of registration"),
    DocumentType.POLICY: ("insurance policy", "certificate of insurance", "policy schedule", "policy number", "policy no", "insured declared value", "period of insurance", "policyholder", "third party liability", "own damage", "premium details"),
    DocumentType.DRIVING_LICENCE: ("driving licence", "driving license", "licence no", "licence number", "license number", "dl no", "driver licence", "valid till", "date of issue"),
    DocumentType.FIR: ("first information report", "fir no", "police station", "complainant", "crime no", "date and time of occurrence"),
    DocumentType.GARAGE_ESTIMATE: ("repair estimate", "estimated cost", "labour charges", "garage estimate", "estimate no", "parts total", "estimate amount"),
    DocumentType.REPAIR_INVOICE: ("tax invoice", "invoice number", "invoice no", "amount payable", "gstin", "total invoice value", "bill amount"),
    DocumentType.ACCIDENT_PHOTOS: ("accident photograph", "damage photograph", "vehicle damage photo"),
}


def classify_text(text: str) -> tuple[DocumentType, float, list[str]]:
    """Return deterministic classification and the indicators supporting it."""
    # PDF extraction can add unpredictable line breaks and repeated whitespace.
    normalized, scores, matches = re.sub(r"\s+", " ", text.lower()), Counter(), {}
    for document_type, indicators in KEYWORDS.items():
        hits = [indicator for indicator in indicators if indicator in normalized]
        if hits:
            scores[document_type], matches[document_type] = len(hits), hits
    if not scores:
        return DocumentType.UNKNOWN, 0.0, []
    detected, score = scores.most_common(1)[0]
    runner_up = scores.most_common(2)[1][1] if len(scores) > 1 else 0
    confidence = min(0.98, 0.55 + (score * 0.16) - (runner_up * 0.10))
    return detected, round(max(0.0, confidence), 2), matches[detected]
