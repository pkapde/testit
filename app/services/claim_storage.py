from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
from uuid import uuid4

from app.core.config import settings
from app.infrastructure.secrets import get_secret
from app.schemas.claim_storage import ClaimStorageResponse, StorageDetails, StoredFileInfo

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".heic"}


def _is_image_file(filename: str, content_type: str | None) -> bool:
    """Determine if a file is an image/vehicle picture based on content-type or extension."""
    if content_type and content_type.lower().startswith("image/"):
        return True
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def _get_azure_blob_service():
    """Retrieve Azure BlobServiceClient if configured, otherwise None."""
    connection_string = get_secret("azure-storage-connection-string", settings.azure_storage_connection_string)
    if connection_string:
        from azure.storage.blob import BlobServiceClient
        return BlobServiceClient.from_connection_string(connection_string)
    if settings.azure_storage_account_url:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        return BlobServiceClient(
            account_url=settings.azure_storage_account_url,
            credential=DefaultAzureCredential(),
        )
    return None


def store_claim_files_and_metadata(
    files: list[tuple[str, bytes, str | None]],
    claim_id: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> ClaimStorageResponse:
    """
    Store uploaded files in Azure Storage categorized by vehicle_pics and other_evidence,
    under a unique {claim_id}_{timestamp} folder. Saves full claim information JSON in
    root folder data/Claim_Data/unique_claim_information.
    """
    # 1. Ensure unique claim ID
    if not claim_id or not claim_id.strip():
        claim_id = f"CLM-{uuid4().hex[:8].upper()}"
    else:
        claim_id = claim_id.strip().upper()

    now = datetime.now(timezone.utc)
    iso_timestamp = now.isoformat()
    time_created = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    folder_timestamp = now.strftime("%Y%m%d_%H%M%S")
    folder_name = f"{claim_id}_{folder_timestamp}"

    current_status = status.strip() if status and status.strip() else "PENDING_VERIFICATION"
    claim_description = (
        description.strip()
        if description and description.strip()
        else f"Claim documentation submission for {claim_id}"
    )

    container_name = settings.azure_storage_container or "claim-documents"
    blob_service = _get_azure_blob_service()

    if not blob_service:
        raise RuntimeError(
            "Azure Storage is not configured. Please configure AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL."
        )

    try:
        container_client = blob_service.get_container_client(container_name)
        container_client.create_container()
    except Exception:
        pass  # Container usually already exists

    container_client = blob_service.get_container_client(container_name)
    storage_backend = "azure_blob_storage"

    vehicle_pics: list[StoredFileInfo] = []
    other_evidence: list[StoredFileInfo] = []

    # 2. Process and upload each file directly to Azure Blob Storage
    from azure.storage.blob import ContentSettings

    for raw_name, content, content_type in files:
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", raw_name or "file")
        file_hash = sha256(content).hexdigest()
        is_pic = _is_image_file(safe_name, content_type)

        category = "vehicle_pics" if is_pic else "other_evidence"
        blob_path = f"{folder_name}/{category}/{safe_name}"

        # Upload strictly to Azure Blob Storage
        blob_client = container_client.get_blob_client(blob_path)
        blob_client.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type or "application/octet-stream"),
        )
        blob_url = blob_client.url

        stored_info = StoredFileInfo(
            filename=safe_name,
            size_bytes=len(content),
            content_type=content_type or ("image/jpeg" if is_pic else "application/pdf"),
            category=category,
            blob_path=blob_path,
            blob_url=blob_url,
            sha256=file_hash,
        )

        if is_pic:
            vehicle_pics.append(stored_info)
        else:
            other_evidence.append(stored_info)

    storage_details = StorageDetails(
        backend=storage_backend,
        container=container_name,
        base_folder=folder_name,
        vehicle_pics_folder=f"{folder_name}/vehicle_pics",
        other_evidence_folder=f"{folder_name}/other_evidence",
    )

    # 3. Create full information JSON in Data/Claim_Data/unique_claim_information
    project_root = Path(__file__).resolve().parents[2]
    metadata_dir = project_root / "Data" / "Claim_Data" / "unique_claim_information"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    json_filename = f"{claim_id}_{folder_timestamp}.json"
    json_path = metadata_dir / json_filename

    response_data = ClaimStorageResponse(
        claim_id=claim_id,
        folder_name=folder_name,
        time_created=time_created,
        iso_timestamp=iso_timestamp,
        status=current_status,
        description=claim_description,
        total_files_uploaded=len(files),
        vehicle_pics_count=len(vehicle_pics),
        other_evidence_count=len(other_evidence),
        storage_details=storage_details,
        vehicle_pics=vehicle_pics,
        other_evidence=other_evidence,
        saved_metadata_path=str(json_path),
    )

    # Write JSON to unique path
    json_content = json.dumps(response_data.model_dump(), indent=2)
    json_path.write_text(json_content, encoding="utf-8")

    # Also maintain latest claim_id.json for immediate lookup convenience
    latest_path = metadata_dir / f"{claim_id}.json"
    latest_path.write_text(json_content, encoding="utf-8")

    logger.info(
        f"Claim {claim_id} files stored in {folder_name}. Metadata saved to {json_path}"
    )

    return response_data
