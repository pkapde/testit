import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from app.main import app

client = TestClient(app)


def _setup_mock_azure():
    mock_blob_service = MagicMock()
    mock_container = MagicMock()
    mock_blob_client = MagicMock()
    mock_blob_client.url = "https://azureaccount.blob.core.windows.net/claim-documents/blob.bin"

    mock_blob_service.get_container_client.return_value = mock_container
    mock_container.get_blob_client.return_value = mock_blob_client
    return mock_blob_service, mock_container, mock_blob_client


def test_upload_claim_to_storage_endpoint_categorizes_files_and_writes_json_only():
    mock_service, mock_container, mock_blob = _setup_mock_azure()

    test_files = [
        ("files", ("front_car.jpg", b"fake image bytes front", "image/jpeg")),
        ("files", ("side_damage.png", b"fake image bytes side", "image/png")),
        ("files", ("survey_report.pdf", b"%PDF-1.4 fake pdf report", "application/pdf")),
        ("files", ("claim_form.pdf", b"%PDF-1.4 fake pdf form", "application/pdf")),
    ]

    with patch("app.services.claim_storage._get_azure_blob_service", return_value=mock_service):
        response = client.post(
            "/api/v1/claims/upload-to-storage",
            data={
                "claim_id": "CLM-TEST-999",
                "description": "Accident claim documentation with car pics and surveyor report",
                "claim_status": "SUBMITTED",
            },
            files=test_files,
        )

    assert response.status_code == 201
    data = response.json()

    # 1. Claim ID & basic fields
    assert data["claim_id"] == "CLM-TEST-999"
    assert data["status"] == "SUBMITTED"
    assert "CLM-TEST-999" in data["folder_name"]
    assert "time_created" in data
    assert data["total_files_uploaded"] == 4
    assert data["vehicle_pics_count"] == 2
    assert data["other_evidence_count"] == 2
    assert data["storage_details"]["backend"] == "azure_blob_storage"

    # 2. Check vehicle_pics categorization in Azure Storage
    pic_names = [p["filename"] for p in data["vehicle_pics"]]
    assert "front_car.jpg" in pic_names
    assert "side_damage.png" in pic_names
    for p in data["vehicle_pics"]:
        assert p["category"] == "vehicle_pics"
        assert "/vehicle_pics/" in p["blob_path"]
        assert p["sha256"]

    # 3. Check other_evidence categorization in Azure Storage
    doc_names = [d["filename"] for d in data["other_evidence"]]
    assert "survey_report.pdf" in doc_names
    assert "claim_form.pdf" in doc_names
    for d in data["other_evidence"]:
        assert d["category"] == "other_evidence"
        assert "/other_evidence/" in d["blob_path"]
        assert d["sha256"]

    # 4. Azure blob upload was invoked for all 4 files
    assert mock_blob.upload_blob.call_count == 4

    # 5. Check that JSON file is saved in Data/Claim_Data/unique_claim_information
    json_path = Path(data["saved_metadata_path"])
    assert json_path.exists()
    assert json_path.suffix == ".json"
    saved_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_json["claim_id"] == "CLM-TEST-999"
    assert saved_json == data  # Sent JSON matches disk JSON exactly

    # 6. Verify NO binary or raw files are saved inside Data folder
    data_dir = json_path.parents[2]  # Data directory
    for file in data_dir.rglob("*"):
        if file.is_file():
            assert file.suffix == ".json", f"Found non-JSON file in Data folder: {file}"


def test_upload_claim_auto_generates_unique_claim_id_at_backend():
    mock_service, _, _ = _setup_mock_azure()

    test_files = [
        ("files", ("vehicle_back.jpeg", b"fake jpeg back", "image/jpeg")),
        ("files", ("insurance_policy.pdf", b"%PDF-1.4 fake policy", "application/pdf")),
    ]

    with patch("app.services.claim_storage._get_azure_blob_service", return_value=mock_service):
        # Call without providing any claim_id
        response = client.post(
            "/api/v1/claims/upload-to-storage",
            files=test_files,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["claim_id"].startswith("CLM-")
    assert len(data["claim_id"]) > 5
    assert data["claim_id"] in data["folder_name"]
    assert data["vehicle_pics_count"] == 1
    assert data["other_evidence_count"] == 1
    assert Path(data["saved_metadata_path"]).exists()


def test_upload_fails_gracefully_when_azure_not_configured():
    with patch("app.services.claim_storage._get_azure_blob_service", return_value=None):
        response = client.post(
            "/api/v1/claims/upload-to-storage",
            data={"claim_id": "CLM-NO-AZURE"},
            files=[("files", ("car.png", b"test content", "image/png"))],
        )

    assert response.status_code == 500
    assert "Azure Storage is not configured" in response.json()["detail"]


def test_upload_claim_persists_all_columns_to_postgres_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.infrastructure.postgres import Base, ClaimStorageRecord

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    mock_service, mock_container, mock_blob = _setup_mock_azure()

    test_files = [
        ("files", ("car_front.jpg", b"image bytes 1", "image/jpeg")),
        ("files", ("repair_estimate.pdf", b"pdf bytes 1", "application/pdf")),
    ]

    detailed_report_payload = {
        "inspector": "Jane Surveyor",
        "estimated_damage_cost": 3400.50,
        "parts_recommended": ["front_bumper", "headlight_assembly"],
        "severity": "MODERATE",
    }

    with patch("app.services.claim_storage._get_azure_blob_service", return_value=mock_service), \
         patch("app.infrastructure.postgres._session_factory", return_value=TestSession):

        # Initial upload does NOT send detailed_report
        response = client.post(
            "/api/v1/claims/upload-to-storage",
            data={
                "claim_id": "CLM-PG-777",
                "user_name": "Rishabh",
                "description": "Front collision on highway with damage report",
                "claim_status": "UNDER_ASSESSMENT",
            },
            files=test_files,
        )

    assert response.status_code == 201
    data = response.json()
    # Untouched older response format
    assert data["claim_id"] == "CLM-PG-777"
    assert data["status"] == "UNDER_ASSESSMENT"
    assert data["total_files_uploaded"] == 2
    assert Path(data["saved_metadata_path"]).exists()

    # 1. Verify directly in the separate PostgreSQL database table (claim_storage_records)
    with TestSession() as session:
        claim_row = session.get(ClaimStorageRecord, "CLM-PG-777")
        assert claim_row is not None
        # Verify columns in PostgreSQL table
        assert claim_row.claim_id == "CLM-PG-777"
        assert claim_row.user_name == "Rishabh"
        assert claim_row.status == "UNDER_ASSESSMENT"
        assert "CLM-PG-777_" in claim_row.vehicle_pic_folder
        assert claim_row.vehicle_pic_folder.endswith("/vehicle_pics")
        assert "CLM-PG-777_" in claim_row.other_document_folder_details
        assert claim_row.other_document_folder_details.endswith("/other_evidence")
        assert claim_row.description == "Front collision on highway with damage report"
        assert claim_row.detailed_report is None
        assert isinstance(claim_row.claim_folder_json, dict)
        assert claim_row.claim_folder_json["claim_id"] == "CLM-PG-777"
        assert claim_row.claim_folder_json["vehicle_pics_count"] == 1
        assert claim_row.claim_folder_json["other_evidence_count"] == 1
        assert claim_row.created_at is not None

    # 2. Test GET /api/v1/claims to fetch all claims and their details JSON from PostgreSQL
    with patch("app.infrastructure.postgres._session_factory", return_value=TestSession):
        get_all_res = client.get("/api/v1/claims")
        assert get_all_res.status_code == 200
        all_claims = get_all_res.json()
        assert len(all_claims) >= 1
        # Find our claim in the list
        matched = next((c for c in all_claims if c.get("claim_id") == "CLM-PG-777"), None)
        assert matched is not None
        assert matched["claim_id"] == "CLM-PG-777"
        assert matched["status"] == "UNDER_ASSESSMENT"
        assert matched["user_name"] == "Rishabh"
        assert matched["storage_details"]["backend"] == "azure_blob_storage"
        assert matched["vehicle_pics_count"] == 1
        assert matched["other_evidence_count"] == 1

    # 3. Test GET /api/v1/claims/{claim_id}/details
    with patch("app.infrastructure.postgres._session_factory", return_value=TestSession):
        get_single_res = client.get("/api/v1/claims/CLM-PG-777/details")
        assert get_single_res.status_code == 200
        single_claim = get_single_res.json()
        assert single_claim["claim_id"] == "CLM-PG-777"
        assert single_claim["status"] == "UNDER_ASSESSMENT"
        assert single_claim["user_name"] == "Rishabh"
        assert single_claim["storage_details"]["base_folder"].startswith("CLM-PG-777_")
        assert len(single_claim["vehicle_pics"]) == 1
        assert len(single_claim["other_evidence"]) == 1


def test_get_claim_details_404_when_not_found():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.infrastructure.postgres import Base

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    with patch("app.infrastructure.postgres._session_factory", return_value=TestSession):
        res = client.get("/api/v1/claims/CLM-NON-EXISTENT-XYZ/details")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]

