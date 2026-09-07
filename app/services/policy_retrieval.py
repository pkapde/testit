"""Local retrieval of approved policy-wording PDFs for coverage explanations."""
from pathlib import Path
import re
from pypdf import PdfReader
from app.core.config import settings


def retrieve_policy_clauses(query: str, limit: int = 4) -> list[dict[str, str]]:
    """Return lexical top matches; only these excerpts are sent to the LLM."""
    if not settings.policy_reference_path:
        return []
    path = Path(settings.policy_reference_path)
    if not path.exists():
        return []
    terms = {term.lower() for term in re.findall(r"[a-zA-Z]{4,}", query)}
    candidates: list[tuple[int, int, str]] = []
    for page_number, page in enumerate(PdfReader(path).pages, start=1):
        text = page.extract_text() or ""
        for paragraph in re.split(r"\n\s*\n", text):
            cleaned = " ".join(paragraph.split())
            if len(cleaned) < 80:
                continue
            score = sum(term in cleaned.lower() for term in terms)
            if score:
                candidates.append((score, page_number, cleaned[:1500]))
    return [{"reference": f"policy-page-{page}", "text": text} for _, page, text in sorted(candidates, reverse=True)[:limit]]
