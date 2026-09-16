from app.schemas.documents import ClaimTriageResult, ClaimValidationResult, TriageQueue
from app.services.review import create_claims_adjuster_review_task, next_claim_status
from app.schemas.documents import ReviewAction


def test_single_claims_adjuster_task_is_created_for_any_automated_route(monkeypatch):
    # Persistence is covered separately; this verifies the one-reviewer stage.
    captured = {}
    class FakeSession:
        def get(self, *_):
            return None
        def add(self, value):
            captured.setdefault("items", []).append(value)
        def flush(self):
            pass
    class Scope:
        def __enter__(self): return FakeSession()
        def __exit__(self, *_): return None
    monkeypatch.setattr("app.services.review.session_scope", lambda: Scope())
    result = ClaimTriageResult(
        validation=ClaimValidationResult(claim_id="CLM-REVIEW-2", required_documents=[], missing_documents=[], documents_received=0, valid_documents=0, invalid_documents=0, overall_status="COMPLETE", files=[]),
        extracted_fields={}, routing_queue=TriageQueue.CLAIMS_OFFICER, routing_reason="Coverage review required.",
    )
    task = create_claims_adjuster_review_task(result)
    assert task is not None
    assert task.stage == "CLAIMS_ADJUSTER_REVIEW"


def test_claims_adjuster_can_make_final_claim_decision():
    assert next_claim_status(ReviewAction.APPROVE_CLAIM) == "APPROVED"
    assert next_claim_status(ReviewAction.REJECT_CLAIM) == "REJECTED"


def test_claims_adjuster_can_request_missing_information():
    assert next_claim_status(ReviewAction.REQUEST_MORE_INFO) == "WAITING_FOR_INFORMATION"
    # Existing UI/API callers remain valid while they migrate to the clearer action.
    assert next_claim_status(ReviewAction.REQUEST_REUPLOAD) == "WAITING_FOR_UPLOAD"
