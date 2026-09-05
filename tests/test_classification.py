import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.schemas.classification import ClassificationCategory, ClassificationResponse, AccidentPhotoCoverage

client = TestClient(app)


def test_classification_endpoint_valid_rc_file():
    response = client.post(
        "/api/v1/claims/classification",
        data={"category_type": "rc"},
        files=[("files", ("rc_document.txt", b"Certificate of Registration Regn No Chassis Number Engine Number", "text/plain"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert data["category_type"] == "registration_certificate"
    assert "is_valid" in data
    assert "description" in data


def test_classification_endpoint_alias_category_normalization():
    aliases = [
        ("rc", "registration_certificate"),
        ("policy", "insurance_policy"),
        ("survey report motor insurance", "survey_report"),
        ("repair estimate details", "repair_estimate"),
        ("driver licence", "driving_licence"),
        ("claim_form", "claim_form"),
        ("repair_invoice", "repair_invoice"),
        ("car pic four side", "accident_photos"),
    ]
    for alias, expected in aliases:
        response = client.post(
            "/api/v1/claims/classification",
            data={"category_type": alias},
            files=[("files", ("sample.txt", f"Sample text for {alias}".encode(), "text/plain"))],
        )
        assert response.status_code == 200
        assert response.json()["category_type"] == expected


def test_classification_endpoint_invalid_category_type():
    response = client.post(
        "/api/v1/claims/classification",
        data={"category_type": "unknown_invalid_category"},
        files=[("files", ("sample.txt", b"Sample content", "text/plain"))],
    )
    assert response.status_code == 422
    assert "Invalid category_type" in response.json()["detail"]


def test_classification_endpoint_invalid_document_returns_error_description():
    # Send a repair invoice text when requesting registration_certificate
    response = client.post(
        "/api/v1/claims/classification",
        data={"category_type": "registration_certificate"},
        files=[("files", ("invoice.txt", b"Tax Invoice bill amount gstin total invoice value", "text/plain"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["error"] is not None
    assert "Invalid" in data["error"] or "not a valid" in data["error"] or "repair_invoice" in data["error"]


def test_classification_endpoint_accident_photos():
    files = [
        ("files", ("front.jpg", b"front view car damage photo", "image/jpeg")),
        ("files", ("rear.jpg", b"rear view car damage photo", "image/jpeg")),
        ("files", ("left.jpg", b"left side car damage photo", "image/jpeg")),
        ("files", ("right.jpg", b"right side car damage photo", "image/jpeg")),
    ]
    response = client.post(
        "/api/v1/claims/classification",
        data={"category_type": "accident_photos"},
        files=files,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["category_type"] == "accident_photos"
    assert data["accident_photo_coverage"] is not None
    assert "all_4_sides_present" in data["accident_photo_coverage"]


def test_classify_with_mocked_azure_openai_response():
    mock_ai_json = {
        "is_valid": True,
        "category_type": "driving_licence",
        "detected_type": "driving_licence",
        "confidence": 0.96,
        "description": "Valid Indian Driving Licence document identified with clear driver details.",
        "error": None,
        "file_assessments": [
            {
                "filename": "dl.png",
                "status": "VALID",
                "detected_content": "driving_licence",
                "notes": "Clear license photo with DL number.",
            }
        ],
        "accident_photo_coverage": None,
    }

    mock_settings = type(
        "MockSettings",
        (),
        {
            "azure_openai_endpoint": "https://demo.openai.azure.com/",
            "azure_openai_api_key": "mock_key_for_test",
            "azure_openai_api_key_secret_name": None,
            "azure_openai_deployment": "gpt-4o",
            "azure_openai_api_version": "2024-10-21",
        },
    )()
    with patch("app.services.document_classifier.settings", mock_settings):
        with patch("app.services.document_classifier.AzureOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_choice = type("Choice", (), {"message": type("Message", (), {"content": json.dumps(mock_ai_json)})()})()
            mock_client.chat.completions.create.return_value = type("ChatResponse", (), {"choices": [mock_choice]})()

            response = client.post(
                "/api/v1/claims/classification",
                data={"category_type": "driving_licence"},
                files=[("files", ("dl.png", b"\x89PNGfakeimagebytes", "image/png"))],
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_valid"] is True
            assert data["detected_type"] == "driving_licence"
            assert data["confidence"] == 0.96
            assert data["error"] is None
