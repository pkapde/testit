from app.schemas.documents import ReviewAction
from app.services.review import next_claim_status


def test_review_actions_have_a_controlled_next_stage():
    assert next_claim_status(ReviewAction.VERIFIED) == "READY_FOR_EXTRACTION"
    assert next_claim_status(ReviewAction.OVERRIDE) == "READY_FOR_EXTRACTION"
    assert next_claim_status(ReviewAction.REQUEST_REUPLOAD) == "WAITING_FOR_UPLOAD"
    assert next_claim_status(ReviewAction.REJECT_DOCUMENT) == "DOCUMENT_REJECTED"
    assert next_claim_status(ReviewAction.ESCALATE_FRAUD) == "FRAUD_REVIEW"
