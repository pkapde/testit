from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "ContractIQ Document Validator")
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    classification_review_threshold: float = float(os.getenv("CLASSIFICATION_REVIEW_THRESHOLD", "0.70"))
    max_upload_size_bytes: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", "10485760"))


settings = Settings()
