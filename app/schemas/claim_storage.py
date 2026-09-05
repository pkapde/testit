from typing import Any
from pydantic import BaseModel, Field


class StoredFileInfo(BaseModel):
    filename: str
    size_bytes: int
    content_type: str | None = None
    category: str  # "vehicle_pics" or "other_evidence"
    blob_path: str
    blob_url: str
    sha256: str


class StorageDetails(BaseModel):
    backend: str
    container: str
    base_folder: str
    vehicle_pics_folder: str
    other_evidence_folder: str


class ClaimStorageResponse(BaseModel):
    claim_id: str
    folder_name: str
    time_created: str
    iso_timestamp: str
    status: str
    description: str
    total_files_uploaded: int
    vehicle_pics_count: int
    other_evidence_count: int
    storage_details: StorageDetails
    vehicle_pics: list[StoredFileInfo] = Field(default_factory=list)
    other_evidence: list[StoredFileInfo] = Field(default_factory=list)
    saved_metadata_path: str
