from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.main import app
from app.services.rag_service import (
    format_policy_to_text,
    load_policy_records,
    resolve_policy_data_file,
    split_with_semantic_chunker,
)


def test_resolve_policy_data_file():
    path = resolve_policy_data_file()
    assert path.is_file()
    assert "Polic" in path.name


def test_load_policy_records():
    policies = load_policy_records()
    assert isinstance(policies, list)
    assert len(policies) >= 3
    first_policy = policies[0]
    assert "policy_number" in first_policy
    assert "policy_holder" in first_policy
    assert "coverage_and_add_ons" in first_policy


def test_format_policy_to_text():
    sample_policy = {
        "policy_number": "POL-TEST-123",
        "policy_holder": {"name": "Test User", "email": "test@example.com"},
        "vehicle_details": {"registration_number": "KA01AB1234", "make": "Tata", "model": "Harrier"},
        "policy_terms": {"policy_type": "Comprehensive", "insured_declared_value_inr": 1200000},
        "coverage_and_add_ons": {"zero_depreciation_cover": True, "engine_gearbox_protection": True},
        "deductibles": {"compulsory_deductible_inr": 1000},
        "claim_rules_and_conditions": {
            "intimation_deadline_hours": 48,
            "cashless_garage_network": ["Test Garage 1"],
            "exclusions": ["Drunk driving"],
        },
    }
    narrative, meta = format_policy_to_text(sample_policy)
    assert "POL-TEST-123" in narrative
    assert "Zero Depreciation Cover: Yes" in narrative
    assert "KA01AB1234" in narrative
    assert meta["policy_number"] == "POL-TEST-123"
    assert meta["holder_name"] == "Test User"


def test_format_policy_to_text_arbitrary_json():
    arbitrary_json = {
        "contractId": "CTR-9988",
        "insuredParty": {
            "fullName": "Jane Doe",
            "tier": "Gold Member"
        },
        "coverageLimits": {
            "maxPayoutUSD": 500000,
            "zeroDeductibleApplicable": True
        },
        "customClauses": [
            "No flood damage outside city limits",
            "Must park in covered garage"
        ],
        "specialDiscounts": None
    }
    narrative, meta = format_policy_to_text(arbitrary_json)
    assert "Insurance Policy Record (CTR-9988)" in narrative
    assert "Contract Id: CTR-9988" in narrative
    assert "Full Name: Jane Doe" in narrative
    assert "Tier: Gold Member" in narrative
    assert "Max Payout Usd: 500000" in narrative
    assert "Zero Deductible Applicable: Yes" in narrative
    assert "Special Discounts: Not specified" in narrative
    assert "No flood damage outside city limits" in narrative
    assert meta["policy_number"] == "CTR-9988"


def test_semantic_chunking_with_fake_embeddings():
    fake_embeddings = DeterministicFakeEmbedding(size=384)
    texts = [
        "Motor Insurance Policy Record: POL-TEST-123. Effective Period: 2026-01-01 to 2027-01-01. "
        "Insured Declared Value is INR 1,200,000. Coverage includes zero depreciation and engine protection. "
        "Claim must be intimating within 48 hours to be valid. Unauthorized commercial usage is excluded."
    ]
    metadatas = [{"policy_number": "POL-TEST-123"}]

    docs = split_with_semantic_chunker(texts, metadatas, fake_embeddings)
    assert len(docs) >= 1
    assert "POL-TEST-123" in docs[0].page_content
    assert docs[0].metadata.get("policy_number") == "POL-TEST-123"


def test_ingest_api_endpoint(monkeypatch):
    fake_embeddings = DeterministicFakeEmbedding(size=384)
    monkeypatch.setattr("app.services.rag_service.get_azure_embeddings", lambda: fake_embeddings)

    with TestClient(app) as client:
        response = client.post("/api/v1/claims/ingest")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["policies_loaded"] >= 3
        assert data["chunks_created"] >= 3


def test_ask_claim_details_streaming_api(monkeypatch):
    fake_embeddings = DeterministicFakeEmbedding(size=384)
    monkeypatch.setattr("app.services.rag_service.get_azure_embeddings", lambda: fake_embeddings)

    # Ingest first with fake embeddings
    from app.services.rag_service import ingest_policy_data
    ingest_policy_data()

    async def mock_stream_claim_details(query: str, k: int = 3):
        for t in ["Policy ", "covers ", "zero ", "depreciation."]:
            yield t

    monkeypatch.setattr("app.api.v1.routes.claims.stream_claim_details", mock_stream_claim_details)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/claims/askClaimDetails",
            json={"query": "Does Rohan Sharma have zero dep cover?"},
        )
        assert response.status_code == 200
        assert "Policy covers zero depreciation." in response.text


def test_ask_claim_details_empty_query():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/claims/askClaimDetails",
            json={"query": "   "},
        )
        assert response.status_code == 400
