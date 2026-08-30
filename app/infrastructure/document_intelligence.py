from app.core.config import settings
from app.infrastructure.secrets import get_secret


def extract_document_text(content: bytes) -> str:
    """Extract OCR text with Azure Document Intelligence's general read model."""
    key = get_secret("azure-document-intelligence-key", settings.document_intelligence_key)
    if not settings.document_intelligence_endpoint:
        raise RuntimeError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT is not configured")
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    if key:
        from azure.core.credentials import AzureKeyCredential
        credential = AzureKeyCredential(key)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
    client = DocumentIntelligenceClient(settings.document_intelligence_endpoint, credential)
    poller = client.begin_analyze_document("prebuilt-read", AnalyzeDocumentRequest(bytes_source=content))
    result = poller.result()
    return "\n".join(page.content or "" for page in result.pages or [])
