from fastapi.testclient import TestClient

from app.main import app


def test_classification_completeness_agent_api_classifies_uploaded_file():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/claims/CLM-UI-1/classification-completeness",
            files={
                "files": (
                    "fir.txt",
                    b"First Information Report FIR No police station complainant",
                    "text/plain",
                )
            },
            data={"expected_documents": "fir"},
        )

    assert response.status_code == 200
    file_result = response.json()["files"][0]
    assert file_result["detected_document"] == "fir"
    assert file_result["status"] == "VALID"
