from collections import Counter
from app.schemas.documents import DocumentType

KEYWORDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.CLAIM_FORM: ("claim form", "claimant", "date of loss", "accident details"),
    DocumentType.RC: ("registration certificate", "registration no", "vehicle class", "chassis no"),
    DocumentType.POLICY: ("insurance policy", "policy number", "insured declared value", "period of insurance"),
    DocumentType.DRIVING_LICENCE: ("driving licence", "driving license", "licence no", "valid till"),
    DocumentType.FIR: ("first information report", "fir no", "police station", "complainant"),
    DocumentType.GARAGE_ESTIMATE: ("repair estimate", "estimated cost", "labour charges", "garage estimate"),
    DocumentType.REPAIR_INVOICE: ("tax invoice", "invoice number", "amount payable", "gstin"),
    DocumentType.ACCIDENT_PHOTOS: ("accident photograph", "damage photograph", "vehicle damage photo"),
}


def classify_text(text: str) -> tuple[DocumentType, float, list[str]]:
    """Return deterministic classification and the indicators supporting it."""
    normalized, scores, matches = text.lower(), Counter(), {}
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
