from dataclasses import dataclass
import os
from dotenv import load_dotenv

# Local development convenience only. Production supplies settings through the
# platform environment, Key Vault, and Managed Identity.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "ContractIQ Document Validator")
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    classification_review_threshold: float = float(os.getenv("CLASSIFICATION_REVIEW_THRESHOLD", "0.70"))
    # When Azure OpenAI is configured, independently verify every document
    # classification. A disagreement never auto-accepts a document.
    llm_always_verify_documents: bool = os.getenv("LLM_ALWAYS_VERIFY_DOCUMENTS", "true").lower() == "true"
    estimate_invoice_variance_threshold: float = float(os.getenv("ESTIMATE_INVOICE_VARIANCE_THRESHOLD", "0.20"))
    max_upload_size_bytes: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", "10485760"))
    policy_reference_path: str | None = os.getenv("POLICY_REFERENCE_PATH")
    # Comma-separated browser origins permitted to call the API. Keep this
    # explicit in production instead of using a wildcard with credentials.
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if origin.strip()
    )
    database_url: str | None = os.getenv("DATABASE_URL")
    azure_key_vault_url: str | None = os.getenv("AZURE_KEY_VAULT_URL")
    database_url_secret_name: str | None = os.getenv("DATABASE_URL_SECRET_NAME")
    azure_storage_connection_string: str | None = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    azure_storage_account_url: str | None = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    azure_storage_container: str = os.getenv("AZURE_STORAGE_CONTAINER", "claim-documents")
    document_intelligence_endpoint: str | None = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    document_intelligence_key: str | None = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    azure_openai_endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_api_key_secret_name: str | None = os.getenv("AZURE_OPENAI_API_KEY_SECRET_NAME")
    azure_openai_deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_embedding_deployment: str | None = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    # Corporate TLS: use the Windows/macOS/Linux system certificate store by
    # default. Alternatively point to an IT-provided PEM CA bundle.
    azure_openai_ca_bundle: str | None = os.getenv("AZURE_OPENAI_CA_BUNDLE")
    azure_openai_use_system_certificates: bool = os.getenv("AZURE_OPENAI_USE_SYSTEM_CERTIFICATES", "true").lower() == "true"
    rag_policy_data_path: str = os.getenv("RAG_POLICY_DATA_PATH", "Data/Rag/policy_details.json")
    langsmith_tracing: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    langsmith_api_key: str | None = os.getenv("LANGSMITH_API_KEY")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "contractiq")
    langsmith_api_key_secret_name: str | None = os.getenv("LANGSMITH_API_KEY_SECRET_NAME")


settings = Settings()
