from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    status: str = Field(..., description="Ingestion status (e.g. success, error)")
    policies_loaded: int = Field(..., description="Number of policies parsed from JSON")
    chunks_created: int = Field(..., description="Number of semantic chunks generated")
    message: str = Field(..., description="Details of the ingestion process")


class AskClaimRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Claim or policy query to ask the RAG pipeline")
    k: int = Field(default=3, ge=1, le=10, description="Number of relevant chunks to retrieve")
