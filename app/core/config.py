from dataclasses import dataclass, field
import logging
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


# A local .env is useful on a developer workstation.  Never load it in a
# deployed service: configuration must come from the hosting environment or
# Key Vault, so an accidentally packaged local DATABASE_URL cannot point an
# Azure workload back to localhost.
if not _is_production():
    load_dotenv()


def _resolve_secret_from_key_vault(secret_name: str | None) -> str | None:
    """Resolve an optional secret with the workload's managed identity.

    Environment values deliberately take precedence. That lets Azure App
    Service/Foundry resolve a Key Vault reference into DATABASE_URL without an
    application-side Key Vault call, while local development keeps using .env.
    """
    vault_url = os.getenv("AZURE_KEY_VAULT_URL")
    if not secret_name or not vault_url:
        return None
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential()).get_secret(secret_name).value
    except Exception as exc:
        logger.warning("Could not resolve configured Key Vault secret %s: %s", secret_name, type(exc).__name__)
        return None


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or _resolve_secret_from_key_vault(os.getenv("DATABASE_URL_SECRET_NAME"))


def _phoenix_endpoint() -> str:
    return os.getenv("PHOENIX_ENDPOINT", "http://127.0.0.1:6006/v1/traces")


def _phoenix_enabled() -> bool:
    enabled = os.getenv("PHOENIX_ENABLED", "false").lower() == "true"
    host = (urlparse(_phoenix_endpoint()).hostname or "").lower()
    if enabled and _is_production() and host in {"localhost", "127.0.0.1", "::1"}:
        logger.warning("Phoenix tracing was disabled because its production endpoint resolves to localhost")
        return False
    return enabled


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
    database_url: str | None = field(default_factory=_database_url)
    # Local-account pilot authentication. Keep disabled while migrating existing
    # demo users, then set AUTH_REQUIRED=true to enforce a signed local session.
    auth_required: bool = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
    local_auth_secret: str | None = os.getenv("LOCAL_AUTH_SECRET")
    local_auth_token_minutes: int = int(os.getenv("LOCAL_AUTH_TOKEN_MINUTES", "480"))
    local_auth_allow_validator_registration: bool = os.getenv("LOCAL_AUTH_ALLOW_VALIDATOR_REGISTRATION", "false").lower() == "true"
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
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    # Phoenix is optional and disabled by default. It exports redacted operational
    # metadata over OTLP to an internally hosted Phoenix instance.
    phoenix_enabled: bool = field(default_factory=_phoenix_enabled)
    phoenix_endpoint: str = field(default_factory=_phoenix_endpoint)
    phoenix_project_name: str = os.getenv("PHOENIX_PROJECT_NAME", "contractiq")
    phoenix_service_name: str = os.getenv("PHOENIX_SERVICE_NAME", "contractiq-backend")
    phoenix_capture_content: bool = os.getenv("PHOENIX_CAPTURE_CONTENT", "false").lower() == "true"


settings = Settings()
