"""Grounded policy-wording enquiry service.

This service deliberately returns only approved local-policy excerpts.  It is
not a claims decision engine and does not expose an LLM to the browser.
"""
from app.schemas.policy import PolicyEnquiryResponse, PolicyEnquirySource
from app.infrastructure.azure_openai import answer_policy_enquiry as llm_answer_policy_enquiry
from app.services.policy_retrieval import retrieve_policy_clauses


def answer_policy_enquiry(query: str, policy_number: str | None = None) -> PolicyEnquiryResponse:
    clauses = retrieve_policy_clauses(query)
    if not clauses:
        return PolicyEnquiryResponse(
            answer=(
                "I could not find a matching passage in the approved policy wording. "
                "Please ask a Claims Adjuster to review the policy schedule and endorsements."
            ),
            sources=[],
            confidence=0.0,
            model="DETERMINISTIC_POLICY_RETRIEVAL",
        )

    policy_label = f" for policy {policy_number}" if policy_number else ""
    excerpts = [
        PolicyEnquirySource(
            title="Approved motor policy wording",
            section=clause["reference"],
            excerpt=clause["text"],
            confidence=round(max(0.55, 0.95 - index * 0.1), 2),
        )
        for index, clause in enumerate(clauses)
    ]
    deterministic_answer = (
        f"The following approved policy-wording excerpts are relevant{policy_label}. "
        "They are informational only; coverage, liability, and payout require Claims Adjuster review."
    )
    llm_answer = llm_answer_policy_enquiry(query=query, clauses=clauses)
    return PolicyEnquiryResponse(
        answer=llm_answer or deterministic_answer,
        sources=excerpts,
        confidence=excerpts[0].confidence,
        model="AZURE_OPENAI_GROUNDED_RAG" if llm_answer else "DETERMINISTIC_POLICY_RETRIEVAL",
    )
