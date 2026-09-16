from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
from typing import Any
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


def save_claim_storage_to_postgres(
    claim_id: str,
    user_name: str | None,
    owner_user_id: str | None,
    status: str,
    vehicle_pic_folder: str,
    other_document_folder_details: str,
    description: str,
    detailed_report: dict | list | None,
    claim_folder_json: dict,
) -> bool:
    """
    Persist claim metadata into separate Azure PostgreSQL table (claim_storage_records).
    Populates:
      - claim_id
      - user_name
      - status
      - vehicle_pic_folder
      - other_document_folder_details
      - description
      - detailed_report (JSON)
      - claim_folder_json (all details under claim folder json in one column as JSON)
    """
    try:
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope
        with session_scope() as session:
            record = session.get(ClaimStorageRecord, claim_id)
            if not record:
                record = ClaimStorageRecord(claim_id=claim_id)
                session.add(record)

            record.user_name = user_name
            record.owner_user_id = owner_user_id
            record.status = status
            record.vehicle_pic_folder = vehicle_pic_folder
            record.other_document_folder_details = other_document_folder_details
            record.description = description
            record.detailed_report = detailed_report
            record.claim_folder_json = claim_folder_json

        logger.info(f"Successfully saved claim storage record {claim_id} to claim_storage_records table.")
        return True
    except Exception as exc:
        logger.warning(f"Could not persist claim storage record {claim_id} to PostgreSQL: {exc}")
        return False


def get_all_claims_json_from_postgres(owner_user_id: str | None = None) -> list[dict]:
    """
    Retrieve all claims and their details JSON from Azure PostgreSQL claim_storage_records table.
    Returns the JSON stored under the claim_folder_json column (the exact details JSON returned after saving files to storage).
    """
    results: list[dict] = []
    try:
        from sqlalchemy import select
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope
        with session_scope() as session:
            stmt = select(ClaimStorageRecord).order_by(ClaimStorageRecord.created_at.desc())
            if owner_user_id:
                stmt = stmt.where(ClaimStorageRecord.owner_user_id == owner_user_id)
            records = session.scalars(stmt).all()
            for r in records:
                if r.claim_folder_json:
                    claim_json = dict(r.claim_folder_json)
                    if r.user_name and "user_name" not in claim_json:
                        claim_json["user_name"] = r.user_name
                    if r.owner_user_id and "owner_user_id" not in claim_json:
                        claim_json["owner_user_id"] = r.owner_user_id
                    results.append(claim_json)
                else:
                    results.append({
                        "claim_id": r.claim_id,
                        "user_name": r.user_name,
                        "status": r.status,
                        "description": r.description,
                        "vehicle_pics_folder": r.vehicle_pic_folder,
                        "other_document_folder_details": r.other_document_folder_details,
                        "detailed_report": r.detailed_report,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    })
    except Exception as exc:
        logger.warning(f"Failed to query all claim records from PostgreSQL: {exc}")

    if not results:
        # Fallback to local files if database is empty or not configured
        project_root = Path(__file__).resolve().parents[2]
        metadata_dir = project_root / "Data" / "Claim_Data" / "unique_claim_information"
        if metadata_dir.exists():
            seen_claim_ids: set[str] = set()
            for json_file in sorted(metadata_dir.glob("CLM-*_*.json"), reverse=True):
                try:
                    claim_json = json.loads(json_file.read_text(encoding="utf-8"))
                    claim_id = str(claim_json.get("claim_id", "")).strip().upper()
                    if claim_id and claim_id in seen_claim_ids:
                        continue
                    if claim_id:
                        seen_claim_ids.add(claim_id)
                    if not owner_user_id or claim_json.get("owner_user_id") == owner_user_id:
                        results.append(claim_json)
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue

    return results


def get_claim_details_json_from_postgres(claim_id: str) -> dict | None:
    """Retrieve details JSON for a single claim from Azure PostgreSQL claim_folder_json column."""
    try:
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope
        with session_scope() as session:
            record = session.get(ClaimStorageRecord, claim_id.strip().upper())
            if record and record.claim_folder_json:
                data = dict(record.claim_folder_json)
                if record.user_name and "user_name" not in data:
                    data["user_name"] = record.user_name
                return data
    except Exception as exc:
        logger.warning(f"Failed to query claim {claim_id} from PostgreSQL: {exc}")

    # Fallback to local file if available
    project_root = Path(__file__).resolve().parents[2]
    metadata_dir = project_root / "Data" / "Claim_Data" / "unique_claim_information"
    latest_file = metadata_dir / f"{claim_id.strip().upper()}.json"
    if latest_file.exists():
        try:
            return json.loads(latest_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def update_claim_detailed_report(claim_id: str, detailed_report: Any) -> bool:
    """Save or update detailed_report for a claim at a later stage in claim_storage_records."""
    try:
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope
        with session_scope() as session:
            record = session.get(ClaimStorageRecord, claim_id.strip().upper())
            if not record:
                return False
            record.detailed_report = detailed_report
        logger.info(f"Updated detailed_report for claim {claim_id} in claim_storage_records table.")
        return True
    except Exception as exc:
        logger.warning(f"Failed to update detailed_report for claim {claim_id}: {exc}")
        return False


def save_completed_workflow_report(claim_id: str, workflow_result: Any) -> str:
    """Merge a completed workflow result into the claim's local metadata JSON.

    Upload metadata is written as soon as Blob Storage accepts the original
    documents. This function is deliberately called only after the automated
    workflow succeeds, so the final JSON contains both the storage manifest
    and the classification, extraction, validation, fraud, coverage, and
    Claims Adjuster routing results.
    """
    normalized_claim_id = claim_id.strip().upper()
    if hasattr(workflow_result, "model_dump"):
        workflow_payload = workflow_result.model_dump(mode="json")
    elif isinstance(workflow_result, dict):
        workflow_payload = workflow_result
    else:
        raise ValueError("workflow_result must be a serializable workflow response")

    project_root = Path(__file__).resolve().parents[2]
    metadata_dir = project_root / "Data" / "Claim_Data" / "unique_claim_information"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    latest_path = metadata_dir / f"{normalized_claim_id}.json"

    claim_payload: dict[str, Any] = {"claim_id": normalized_claim_id}
    if latest_path.exists():
        try:
            previous_payload = json.loads(latest_path.read_text(encoding="utf-8"))
            if isinstance(previous_payload, dict):
                claim_payload = previous_payload
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read existing local metadata for claim %s", normalized_claim_id)

    completed_at = datetime.now(timezone.utc).isoformat()
    claim_payload["workflow"] = workflow_payload
    claim_payload["workflow_completed_at"] = completed_at
    claim_payload["workflow_status"] = "COMPLETED"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    completed_path = metadata_dir / f"{normalized_claim_id}_{timestamp}_workflow.json"
    serialized_payload = json.dumps(claim_payload, indent=2, ensure_ascii=False)
    completed_path.write_text(serialized_payload, encoding="utf-8")
    latest_path.write_text(serialized_payload, encoding="utf-8")

    try:
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope

        with session_scope() as session:
            record = session.get(ClaimStorageRecord, normalized_claim_id)
            if record:
                record.detailed_report = workflow_payload
                record.claim_folder_json = claim_payload
    except Exception as exc:
        # Local JSON is the required durable fallback when PostgreSQL is not configured.
        logger.warning("Could not save completed workflow for claim %s to PostgreSQL: %s", normalized_claim_id, exc)

    logger.info("Saved completed workflow JSON for claim %s to %s", normalized_claim_id, completed_path)
    return str(completed_path)


def set_claim_processing_status(claim_id: str, workflow_status: str, error: str | None = None) -> None:
    """Persist background-processing progress without exposing internal errors to users."""
    normalized_claim_id = claim_id.strip().upper()
    project_root = Path(__file__).resolve().parents[2]
    latest_path = project_root / "Data" / "Claim_Data" / "unique_claim_information" / f"{normalized_claim_id}.json"
    payload: dict[str, Any] = {"claim_id": normalized_claim_id}
    if latest_path.exists():
        try:
            loaded = json.loads(latest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read processing status metadata for claim %s", normalized_claim_id)
    payload["status"] = workflow_status
    payload["workflow_status"] = workflow_status
    if error:
        payload["workflow_error"] = error[:500]
    latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        from app.infrastructure.postgres import ClaimStorageRecord, session_scope

        with session_scope() as session:
            record = session.get(ClaimStorageRecord, normalized_claim_id)
            if record:
                record.status = workflow_status
                record.claim_folder_json = payload
    except Exception as exc:
        logger.warning("Could not update processing status for claim %s in PostgreSQL: %s", normalized_claim_id, exc)


def save_claim_review_decision_to_local_metadata(
    claim_id: str,
    *,
    status: str,
    action: str,
    reviewer_id: str,
    comment: str,
    resolved_at: str,
    deductible: str | None = None,
    approved_amount: str | None = None,
    requested_documents: list[str] | None = None,
) -> None:
    """Keep the local JSON fallback aligned with a durable adjuster decision."""
    project_root = Path(__file__).resolve().parents[2]
    latest_path = project_root / "Data" / "Claim_Data" / "unique_claim_information" / f"{claim_id.strip().upper()}.json"
    if not latest_path.exists():
        return
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        payload["status"] = status
        payload["workflow_status"] = status
        human_review = {
            "stage": "CLAIMS_ADJUSTER_REVIEW",
            "decision": action,
            "reviewer_id": reviewer_id,
            "comment": comment,
            "resolved_at": resolved_at,
        }
        if action == "APPROVE_CLAIM":
            human_review["deductible"] = deductible
            human_review["approved_amount"] = approved_amount
        if action in {"REQUEST_MORE_INFO", "REQUEST_REUPLOAD"}:
            human_review["requested_documents"] = list(requested_documents or [])
            human_review["information_request"] = {
                "message": comment,
                "requested_documents": list(requested_documents or []),
                "claimant_next_step": "Upload the requested evidence so the validator can resume the review.",
            }
        payload["human_review"] = human_review
        latest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not update local review decision for claim %s: %s", claim_id, exc)


def store_claim_files_and_metadata(
    files: list[tuple[str, bytes, str | None]],
    claim_id: str | None = None,
    user_name: str | None = None,
    owner_user_id: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> ClaimStorageResponse:
    """
    Store uploaded files in Azure Storage categorized by vehicle_pics and other_evidence,
    under a unique {claim_id}_{timestamp} folder. Saves full claim information JSON in
    root folder data/Claim_Data/unique_claim_information and persists the record to Azure PostgreSQL.
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

    # Write JSON to unique path (older data format completely untouched)
    response_payload = response_data.model_dump()
    # Response remains backward-compatible; the owner is persisted only in
    # metadata and PostgreSQL, never echoed to an unrelated caller.
    if owner_user_id:
        response_payload["owner_user_id"] = owner_user_id
    json_content = json.dumps(response_payload, indent=2)
    json_path.write_text(json_content, encoding="utf-8")

    # Also maintain latest claim_id.json for immediate lookup convenience
    latest_path = metadata_dir / f"{claim_id}.json"
    latest_path.write_text(json_content, encoding="utf-8")

    # 4. Save to separate PostgreSQL table (claim_storage_records) for blob storage uploads
    # Note: detailed_report is saved at a later stage, so it is initially None
    db_saved = save_claim_storage_to_postgres(
        claim_id=claim_id,
        user_name=user_name.strip() if user_name and user_name.strip() else None,
        owner_user_id=owner_user_id,
        status=current_status,
        vehicle_pic_folder=storage_details.vehicle_pics_folder,
        other_document_folder_details=storage_details.other_evidence_folder,
        description=claim_description,
        detailed_report=None,
        claim_folder_json=response_payload,
    )

    logger.info(
        f"Claim {claim_id} files stored in {folder_name}. Metadata saved to {json_path}. Dedicated DB record saved: {db_saved}"
    )

    return response_data
