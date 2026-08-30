"""Secret resolution for local development and Azure Key Vault production deployments."""
from functools import lru_cache
from app.core.config import settings


@lru_cache(maxsize=32)
def get_secret(secret_name: str, local_value: str | None = None) -> str | None:
    """Use a local value in development; otherwise retrieve a named Key Vault secret via Managed Identity."""
    if local_value:
        return local_value
    if not secret_name or not settings.azure_key_vault_url:
        return None
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    client = SecretClient(vault_url=settings.azure_key_vault_url, credential=DefaultAzureCredential())
    return client.get_secret(secret_name).value
