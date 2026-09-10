import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from app.core.config import settings
from app.infrastructure.secrets import get_secret

logger = logging.getLogger(__name__)

# Cached in-memory vector store instance
_VECTOR_STORE: Any = None


def is_azure_openai_configured() -> bool:
    """Check if Azure OpenAI endpoint and keys are configured."""
    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    return bool(settings.azure_openai_endpoint and api_key and settings.azure_openai_deployment)


def get_azure_embeddings():
    """Instantiate AzureOpenAIEmbeddings using text_embedding_small deployment."""
    from langchain_openai import AzureOpenAIEmbeddings

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    return AzureOpenAIEmbeddings(
        azure_deployment=settings.azure_openai_embedding_deployment,
        azure_endpoint=settings.azure_openai_endpoint or "https://mock.openai.azure.com/",
        api_key=api_key or "mock-key",
        api_version=settings.azure_openai_api_version,
    )


def get_azure_llm():
    """Instantiate AzureChatOpenAI using the configured deployment."""
    from langchain_openai import AzureChatOpenAI

    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    return AzureChatOpenAI(
        azure_deployment=settings.azure_openai_deployment or "gpt-4o",
        azure_endpoint=settings.azure_openai_endpoint or "https://mock.openai.azure.com/",
        api_key=api_key or "mock-key",
        api_version=settings.azure_openai_api_version,
        temperature=0.1,
        streaming=True,
    )


def resolve_policy_data_file(custom_path: str | Path | None = None) -> Path:
    """Find the policy JSON file checking configured path and common variations."""
    candidates = []
    if custom_path:
        candidates.append(Path(custom_path))
    candidates.extend([
        Path(settings.rag_policy_data_path),
        Path("Data/Rag/Policu_details.json"),
        Path("Data/Rag/Policy_details.json"),
    ])

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Policy details JSON not found. Checked: {[str(c) for c in candidates]}"
    )


def load_policy_records(file_path: str | Path | None = None) -> list[dict]:
    """Read and parse the policy records from JSON file."""
    path = resolve_policy_data_file(file_path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # In case root JSON is wrapped in a dict
        data = data.get("policies", [data])
    return data


def _humanize_key(key: str) -> str:
    """Convert snake_case, camelCase, or dash-separated keys to human-readable titles."""
    import re
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', str(key))
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    words = s2.replace('-', '_').replace('.', '_').split('_')
    return ' '.join(w.capitalize() for w in words if w)


def json_to_semantic_text(data: Any, indent: int = 0) -> str:
    """Recursively convert any arbitrary JSON structure (dict, list, primitive) into rich semantic text."""
    prefix = "  " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for k, v in data.items():
            readable_k = _humanize_key(str(k))
            if isinstance(v, dict):
                sub_text = json_to_semantic_text(v, indent + 1)
                lines.append(f"{prefix}{readable_k}:\n{sub_text}")
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{prefix}{readable_k}: None")
                elif all(isinstance(item, (str, int, float, bool)) for item in v):
                    formatted_items = [("Yes" if item is True else "No" if item is False else str(item)) for item in v]
                    lines.append(f"{prefix}{readable_k}: {', '.join(formatted_items)}")
                else:
                    lines.append(f"{prefix}{readable_k}:")
                    for idx, item in enumerate(v, 1):
                        lines.append(f"{prefix}  - Item {idx}:")
                        lines.append(json_to_semantic_text(item, indent + 2))
            elif isinstance(v, bool):
                lines.append(f"{prefix}{readable_k}: {'Yes' if v else 'No'}")
            elif v is None:
                lines.append(f"{prefix}{readable_k}: Not specified")
            else:
                lines.append(f"{prefix}{readable_k}: {v}")
        return "\n".join(lines)
    elif isinstance(data, list):
        lines = []
        for idx, item in enumerate(data, 1):
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- Item {idx}:")
                lines.append(json_to_semantic_text(item, indent + 1))
            else:
                val = "Yes" if item is True else "No" if item is False else str(item)
                lines.append(f"{prefix}- {val}")
        return "\n".join(lines)
    else:
        return f"{prefix}{data}"


def _extract_metadata(data: Any) -> dict[str, Any]:
    """Dynamically discover key identifiers from any arbitrary JSON structure."""
    meta: dict[str, Any] = {}
    if not isinstance(data, dict):
        return meta

    def find_field(d: dict, candidate_names: set[str]) -> str | None:
        for k, v in d.items():
            clean_k = str(k).lower().replace("_", "").replace("-", "")
            if clean_k in candidate_names and isinstance(v, (str, int, float)):
                return str(v)
            if isinstance(v, dict):
                res = find_field(v, candidate_names)
                if res:
                    return res
        return None

    policy_id = find_field(data, {
        "policynumber", "policyid", "policy", "id", "claimid",
        "contractnumber", "contractid", "referencenumber", "refno",
    })
    if policy_id:
        meta["policy_number"] = policy_id

    holder = find_field(data, {"name", "holdername", "policyholdername", "customername", "insuredname", "clientname"})
    if holder:
        meta["holder_name"] = holder

    vehicle = find_field(data, {"registrationnumber", "registrationno", "regnumber", "vehicleregistration", "plateno"})
    if vehicle:
        meta["vehicle_registration"] = vehicle

    return meta


def format_policy_to_text(policy: Any) -> tuple[str, dict]:
    """Dynamically convert any policy JSON object into rich semantic text and metadata."""
    if not isinstance(policy, (dict, list)):
        return str(policy), {}

    meta = _extract_metadata(policy)
    header = f"Insurance Policy Record ({meta.get('policy_number', 'Document')}):"
    body = json_to_semantic_text(policy)
    narrative = f"{header}\n{body}".strip()
    return narrative, meta


def split_with_semantic_chunker(
    texts: list[str],
    metadatas: list[dict],
    embeddings: Any,
) -> list[Document]:
    """Perform semantic chunking on the given policy texts."""
    from langchain_experimental.text_splitter import SemanticChunker

    chunker = SemanticChunker(
        embeddings=embeddings,
        breakpoint_threshold_type="percentile",
    )
    docs = chunker.create_documents(texts=texts, metadatas=metadatas)
    return docs


def build_vector_store(docs: list[Document], embeddings: Any):
    """Build and return a vector store from document chunks."""
    try:
        from langchain_community.vectorstores import FAISS

        logger.info("Initializing FAISS vector store with %d chunks...", len(docs))
        return FAISS.from_documents(docs, embeddings)
    except Exception as exc:
        logger.warning("FAISS initialization failed (%s). Falling back to InMemoryVectorStore.", exc)
        from langchain_core.vectorstores import InMemoryVectorStore

        vector_store = InMemoryVectorStore(embeddings)
        vector_store.add_documents(docs)
        return vector_store


def ingest_policy_data(file_path: str | Path | None = None) -> tuple[int, int]:
    """Ingest JSON policies, apply semantic chunking, and index into vector store.

    Returns (number_of_policies, number_of_chunks).
    """
    global _VECTOR_STORE

    policies = load_policy_records(file_path)
    if not policies:
        raise ValueError("No policy records found in JSON data.")

    texts: list[str] = []
    metadatas: list[dict] = []
    for policy in policies:
        narrative, meta = format_policy_to_text(policy)
        texts.append(narrative)
        metadatas.append(meta)

    embeddings = get_azure_embeddings()
    chunks = split_with_semantic_chunker(texts, metadatas, embeddings)
    _VECTOR_STORE = build_vector_store(chunks, embeddings)

    logger.info("Successfully ingested %d policies into %d semantic chunks.", len(policies), len(chunks))
    return len(policies), len(chunks)


def get_vector_store():
    """Retrieve the cached vector store or auto-ingest if not yet loaded."""
    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        logger.info("Vector store not initialized yet. Auto-ingesting policy data...")
        ingest_policy_data()
    return _VECTOR_STORE


async def stream_claim_details(query: str, k: int = 3) -> AsyncGenerator[str, None]:
    """Query the RAG pipeline and yield streamed response tokens."""
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": k})

    llm = get_azure_llm()

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an expert motor insurance claim and policy assistant for ContractIQ.\n"
            "Use the retrieved policy details below to provide an accurate, clear, and direct answer.\n"
            "Include specific numbers, coverage details (IDV, Zero Dep, deductibles, deadlines), and names whenever relevant.\n"
            "If the context does not contain sufficient details to answer, state that clearly.\n\n"
            "Policy Context:\n{context}",
        ),
        ("human", "{question}"),
    ])

    def format_docs(docs: list[Document]) -> str:
        return "\n\n---\n\n".join(doc.page_content for doc in docs)

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    async for chunk in chain.astream(query):
        yield chunk
