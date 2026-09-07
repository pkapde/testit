from fastapi import APIRouter

from app.schemas.policy import PolicyEnquiryRequest, PolicyEnquiryResponse
from app.services.policy_enquiry import answer_policy_enquiry

router = APIRouter(prefix="/policy", tags=["policy"])


@router.post("/enquiry", response_model=PolicyEnquiryResponse)
async def policy_enquiry(request: PolicyEnquiryRequest) -> PolicyEnquiryResponse:
    """Retrieve approved policy wording for the customer portal.

    The endpoint provides informational, grounded excerpts only. It does not
    decide a claim or return a payout decision.
    """
    return answer_policy_enquiry(request.query, request.policyNumber)
