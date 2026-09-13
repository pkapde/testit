"""Grounded policy RAG with Azure OpenAI and safe enterprise TLS handling."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import ssl
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from app.core.config import settings
from app.infrastructure.secrets import get_secret

logger = logging.getLogger(__name__)
_VECTOR_STORE: Any = None
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RagConfigurationError(RuntimeError):
    """A safe, actionable error for missing RAG or enterprise network setup."""


def _azure_credentials(*, require_embeddings: bool) -> tuple[str, str]:
    api_key = get_secret(settings.azure_openai_api_key_secret_name, settings.azure_openai_api_key)
    if not settings.azure_openai_endpoint:
        raise RagConfigurationError("AZURE_OPENAI_ENDPOINT is required for the RAG service.")
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    parsed_endpoint = urlparse(endpoint)
    # AzureOpenAIEmbeddings and AzureChatOpenAI use Azure OpenAI's deployment
    # API. A Foundry *project* endpoint has a different `/openai/v1` contract;
    # accepting it here produces opaque Azure 400 responses during indexing.
    if (
        parsed_endpoint.hostname and parsed_endpoint.hostname.endswith(".services.ai.azure.com")
    ) or "/api/projects/" in parsed_endpoint.path:
        raise RagConfigurationError(
            "AZURE_OPENAI_ENDPOINT must be an Azure OpenAI resource endpoint such as "
            "https://<resource>.openai.azure.com/, not a Foundry project endpoint "
            "containing services.ai.azure.com/api/projects."
        )
    if settings.azure_openai_api_version == "2023-05-15":
        raise RagConfigurationError(
            "AZURE_OPENAI_API_VERSION=2023-05-15 does not support text-embedding-3 models. "
            "Use a current Azure OpenAI API version, for example 2024-02-01 or a later version "
            "supported by your Azure OpenAI resource."
        )
    if not api_key:
        raise RagConfigurationError("Azure OpenAI credentials are not configured. Set AZURE_OPENAI_API_KEY or its Key Vault secret name.")
    if not settings.azure_openai_deployment:
        raise RagConfigurationError("AZURE_OPENAI_DEPLOYMENT is required for RAG answers.")
    if require_embeddings and not settings.azure_openai_embedding_deployment:
        raise RagConfigurationError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is required to index policy documents.")
    return endpoint, api_key


def is_azure_openai_configured() -> bool:
    """Return true only when both chat and embedding deployments are configured."""
    try:
        _azure_credentials(require_embeddings=True)
    except RagConfigurationError:
        return False
    return True


def _trusted_http_client():
    """Create a verified HTTP client that supports organisation-managed CA roots."""
    import httpx

    verify: ssl.SSLContext | str | bool = True
    if settings.azure_openai_ca_bundle:
        bundle = Path(settings.azure_openai_ca_bundle)
        if not bundle.is_file():
            raise RagConfigurationError("AZURE_OPENAI_CA_BUNDLE does not point to an IT-provided PEM certificate bundle.")
        verify = str(bundle)
    elif settings.azure_openai_use_system_certificates:
        try:
            import truststore
            verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError as exc:
            raise RagConfigurationError(
                "Corporate certificate support requires the truststore package. Run `py -m pip install -r requirements.txt`."
            ) from exc
    return httpx.Client(verify=verify, timeout=httpx.Timeout(60.0, connect=20.0))


def get_azure_embeddings():
    """Build the Azure embeddings client using explicit, validated configuration."""
    try:
        from langchain_openai import AzureOpenAIEmbeddings
    except ImportError as exc:
        raise RagConfigurationError("RAG dependencies are missing. Run `py -m pip install -r requirements.txt`.") from exc

    endpoint, api_key = _azure_credentials(require_embeddings=True)
    return AzureOpenAIEmbeddings(
        azure_deployment=settings.azure_openai_embedding_deployment,
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=settings.azure_openai_api_version,
        http_client=_trusted_http_client(),
    )


def get_azure_llm():
    """Build the Azure chat client using verified TLS; it never falls back to mock credentials."""
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise RagConfigurationError("RAG dependencies are missing. Run `py -m pip install -r requirements.txt`.") from exc

    endpoint, api_key = _azure_credentials(require_embeddings=False)
    return AzureChatOpenAI(
        azure_deployment=settings.azure_openai_deployment,
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=settings.azure_openai_api_version,
        temperature=0.1,
        streaming=True,
        http_client=_trusted_http_client(),
    )


def _candidate_paths(custom_path: str | Path | None) -> list[Path]:
    candidates: list[Path] = []
    for raw_path in (custom_path, settings.rag_policy_data_path, "Data/Rag/policy_details.json", "Data/Rag/Policu_details.json"):
        if not raw_path:
            continue
        path = Path(raw_path)
        candidates.append(path)
        if not path.is_absolute():
            candidates.append(_PROJECT_ROOT / path)
    return list(dict.fromkeys(candidates))


def resolve_policy_data_file(custom_path: str | Path | None = None) -> Path:
    """Locate the policy corpus from any working directory with a clear error."""
    candidates = _candidate_paths(custom_path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Policy details JSON not found. Checked: {[str(path) for path in candidates]}")


def load_policy_records(file_path: str | Path | None = None) -> list[dict[str, Any]]:
    path = resolve_policy_data_file(file_path)
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if isinstance(data, dict):
        data = data.get("policies", [data])
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Policy details JSON must contain a list of policy records.")
    return data


def _humanize_key(key: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(key))
    second_pass = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass)
    return " ".join(word.capitalize() for word in second_pass.replace("-", "_").replace(".", "_").split("_") if word)


def json_to_semantic_text(data: Any, indent: int = 0) -> str:
    prefix = "  " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            label = _humanize_key(str(key))
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{label}:")
                lines.append(json_to_semantic_text(value, indent + 1))
            elif value is None:
                lines.append(f"{prefix}{label}: Not specified")
            elif isinstance(value, bool):
                lines.append(f"{prefix}{label}: {'Yes' if value else 'No'}")
            else:
                lines.append(f"{prefix}{label}: {value}")
        return "\n".join(lines)
    if isinstance(data, list):
        return "\n".join(f"{prefix}- {json_to_semantic_text(item, indent + 1).lstrip()}" for item in data) or f"{prefix}None"
    return f"{prefix}{data}"


def _extract_metadata(data: Any) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not isinstance(data, dict):
        return metadata

    def find_field(value: Any, candidates: set[str]) -> str | None:
        if not isinstance(value, dict):
            return None
        for key, item in value.items():
            clean_key = str(key).lower().replace("_", "").replace("-", "")
            if clean_key in candidates and isinstance(item, (str, int, float)):
                return str(item)
            found = find_field(item, candidates)
            if found:
                return found
        return None

    values = {
        "policy_number": {"policynumber", "policyid", "policy", "id", "contractnumber", "contractid", "referencenumber", "refno"},
        "holder_name": {"name", "holdername", "policyholdername", "customername", "insuredname", "clientname"},
        "vehicle_registration": {"registrationnumber", "registrationno", "regnumber", "vehicleregistration", "plateno"},
    }
    for name, candidates in values.items():
        found = find_field(data, candidates)
        if found:
            metadata[name] = found
    return metadata


def format_policy_to_text(policy: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(policy, (dict, list)):
        return str(policy), {}
    metadata = _extract_metadata(policy)
    return f"Insurance Policy Record ({metadata.get('policy_number', 'Document')}):\n{json_to_semantic_text(policy)}".strip(), metadata


def _fallback_chunks(texts: list[str], metadatas: list[dict[str, Any]], chunk_size: int = 1200) -> list[Document]:
    documents: list[Document] = []
    for text, metadata in zip(texts, metadatas):
        for start in range(0, max(len(text), 1), chunk_size):
            documents.append(Document(page_content=text[start:start + chunk_size], metadata=dict(metadata)))
    return documents


def split_with_semantic_chunker(texts: list[str], metadatas: list[dict[str, Any]], embeddings: Any) -> list[Document]:
    """Use semantic chunks when available; remain usable with deterministic chunks otherwise."""
    if len(texts) != len(metadatas):
        raise ValueError("Each policy text must have matching metadata.")
    try:
        from langchain_experimental.text_splitter import SemanticChunker
    except ImportError:
        logger.warning("SemanticChunker is unavailable; using deterministic policy chunks.")
        return _fallback_chunks(texts, metadatas)
    return SemanticChunker(embeddings=embeddings, breakpoint_threshold_type="percentile").create_documents(texts=texts, metadatas=metadatas)


def build_vector_store(docs: list[Document], embeddings: Any):
    if not docs:
        raise ValueError("The policy corpus produced no searchable chunks.")
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError:
        logger.warning("FAISS is not installed; using an in-memory vector store.")
        from langchain_core.vectorstores import InMemoryVectorStore
        store = InMemoryVectorStore(embeddings)
        store.add_documents(docs)
        return store
    # Do not mask embedding/authentication/API failures as a FAISS problem.
    return FAISS.from_documents(docs, embeddings)


def ingest_policy_data(file_path: str | Path | None = None) -> tuple[int, int]:
    global _VECTOR_STORE
    policies = load_policy_records(file_path)
    if not policies:
        raise ValueError("No policy records found in the configured JSON file.")
    narratives_and_metadata = [format_policy_to_text(policy) for policy in policies]
    texts = [item[0] for item in narratives_and_metadata]
    metadatas = [item[1] for item in narratives_and_metadata]
    embeddings = get_azure_embeddings()
    chunks = split_with_semantic_chunker(texts, metadatas, embeddings)
    _VECTOR_STORE = build_vector_store(chunks, embeddings)
    logger.info("Indexed %d policy records into %d chunks.", len(policies), len(chunks))
    return len(policies), len(chunks)


def get_vector_store():
    if _VECTOR_STORE is None:
        ingest_policy_data()
    return _VECTOR_STORE


async def stream_claim_details(query: str, k: int = 3) -> AsyncGenerator[str, None]:
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": k})
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a motor-insurance policy assistant. Answer only from the retrieved policy context. "
                   "State clearly when the context is insufficient. Do not make a final coverage, fraud, liability, or payout decision.\n\nPolicy context:\n{context}"),
        ("human", "{question}"),
    ])
    chain = {"context": retriever | (lambda docs: "\n\n---\n\n".join(doc.page_content for doc in docs)), "question": RunnablePassthrough()} | prompt | get_azure_llm() | StrOutputParser()
    async for chunk in chain.astream(query):
        yield chunk
