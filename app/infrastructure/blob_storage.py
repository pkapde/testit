from hashlib import sha256
from app.core.config import settings
from app.infrastructure.secrets import get_secret


def upload_claim_document(claim_id: str, file_name: str, content: bytes, content_type: str | None = None) -> tuple[str, str]:
    """Upload original bytes and return the immutable content hash and blob URI."""
    connection_string = get_secret("azure-storage-connection-string", settings.azure_storage_connection_string)
    if not connection_string and not settings.azure_storage_account_url:
        raise RuntimeError("Configure AZURE_STORAGE_ACCOUNT_URL with Managed Identity or AZURE_STORAGE_CONNECTION_STRING")
    from azure.storage.blob import BlobServiceClient, ContentSettings
    digest = sha256(content).hexdigest()
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    blob_name = f"claims/{claim_id}/{digest}-{safe_name}"
    if connection_string:
        service = BlobServiceClient.from_connection_string(connection_string)
    else:
        from azure.identity import DefaultAzureCredential
        service = BlobServiceClient(account_url=settings.azure_storage_account_url, credential=DefaultAzureCredential())
    container = service.get_container_client(settings.azure_storage_container)
    try:
        container.create_container()
    except Exception:
        pass  # Container normally already exists; Azure reports a conflict in that case.
    blob = container.get_blob_client(blob_name)
    blob.upload_blob(content, overwrite=False, content_settings=ContentSettings(content_type=content_type or "application/octet-stream"))
    return digest, blob.url
