from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.postgres import Base, ClaimRecord, ClaimStorageRecord, ReviewTaskRecord
from app.schemas.documents import ReviewAction
from app.services.review import resolve_review_task


def test_adjuster_decision_updates_claim_storage_record_for_portals():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    with TestSession() as session:
        session.add(ClaimRecord(claim_id="CLM-DECISION-1", status="COMPLETE"))
        session.add(
            ClaimStorageRecord(
                claim_id="CLM-DECISION-1",
                status="PENDING_VERIFICATION",
                claim_folder_json={
                    "claim_id": "CLM-DECISION-1",
                    "status": "PENDING_VERIFICATION",
                    "workflow": {"extracted_fields": {"estimate.pdf": {"estimate_total": "40120.00"}}},
                },
            )
        )
        session.add(
            ReviewTaskRecord(
                task_id="task-decision-1",
                claim_id="CLM-DECISION-1",
                stage="CLAIMS_ADJUSTER_REVIEW",
                status="OPEN",
                reason="Ready for decision.",
                evidence={},
            )
        )
        session.commit()

    with patch("app.infrastructure.postgres._session_factory", return_value=TestSession), patch(
        "app.services.claim_storage.save_claim_review_decision_to_local_metadata"
    ) as save_local:
        response = resolve_review_task(
            "task-decision-1",
            ReviewAction.APPROVE_CLAIM,
            "adjuster-1",
            "Evidence reviewed and approved.",
            deductible=500,
        )

    assert response.resumed_to == "APPROVED"
    assert response.approved_amount == "39620.00"
    with TestSession() as session:
        assert session.get(ClaimRecord, "CLM-DECISION-1").status == "APPROVED"
        stored = session.get(ClaimStorageRecord, "CLM-DECISION-1")
        assert stored.status == "APPROVED"
        assert stored.claim_folder_json["status"] == "APPROVED"
        assert stored.claim_folder_json["human_review"]["decision"] == "APPROVE_CLAIM"
        assert stored.claim_folder_json["human_review"]["approved_amount"] == "39620.00"
    save_local.assert_called_once()
