"""
VisionX AI Analyzer — Configuration
Centralised settings loaded from .env
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List, Optional, Union, Any
from pathlib import Path

# Project root: d:/ml/visionx-ai
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Application
    app_env: str = Field("development", validation_alias="APP_ENV")
    app_host: str = Field("0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(8000, validation_alias="APP_PORT")
    secret_key: str = Field("change-me", validation_alias="SECRET_KEY")
    debug: bool = Field(False, validation_alias="VISIONX_DEBUG")

    # Database
    database_url: str = Field(
        f"sqlite+aiosqlite:///{str(BASE_DIR / 'visionx.db').replace('\\', '/')}",
        validation_alias="DATABASE_URL",
    )

    # Storage
    upload_dir: Path = Field(BASE_DIR / "uploads", validation_alias="UPLOAD_DIR")
    output_dir: Path = Field(BASE_DIR / "outputs", validation_alias="OUTPUT_DIR")
    weights_dir: Path = Field(BASE_DIR / "weights", validation_alias="WEIGHTS_DIR")
    max_file_size_mb: int = Field(100, validation_alias="MAX_FILE_SIZE_MB")

    # AI Models
    general_model: str = Field("yolo26n.pt", validation_alias="GENERAL_MODEL")
    human_model: str = Field("yolo26n.pt", validation_alias="HUMAN_MODEL")
    ship_model: str = Field("yolo26n.pt", validation_alias="SHIP_MODEL")
    container_model: str = Field("yolo26n.pt", validation_alias="CONTAINER_MODEL")
    container_condition_model: Optional[str] = Field(None, validation_alias="CONTAINER_CONDITION_MODEL")

    pose_model: str = "yolo26n-pose.pt"
    inference_timeout: int = 120
    output_ttl_seconds: int = 3600
    report_dir: Path = BASE_DIR / 'reports'

    # Inference defaults
    default_confidence: float = Field(0.50, validation_alias="DEFAULT_CONFIDENCE")
    default_iou: float = Field(0.45, validation_alias="DEFAULT_IOU")
    max_detections: int = Field(300, validation_alias="MAX_DETECTIONS")

    # Rate Limiting
    rate_limit_inference: str = Field("30/minute", validation_alias="RATE_LIMIT_INFERENCE")

    # CORS
    cors_origins: Union[List[str], str] = Field(
        default=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
        validation_alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # Auth
    auth_enabled: bool = Field(False, validation_alias="AUTH_ENABLED")
    admin_username: str = Field("admin", validation_alias="ADMIN_USERNAME")
    admin_password: str = Field("changeme", validation_alias="ADMIN_PASSWORD")

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("upload_dir", "output_dir", "weights_dir", "report_dir", mode="after")
    @classmethod
    def absolute_storage(cls, value):
        return value if value.is_absolute() else BASE_DIR / value

    def resolve_model_path(self, model_filename: str) -> Path:
        """Resolve a model filename to its full path."""
        p = Path(model_filename)
        if p.is_absolute():
            return p
        return self.weights_dir / p

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()

# Ensure directories exist
for _dir in (settings.upload_dir, settings.output_dir, settings.weights_dir, settings.report_dir):
    _dir.mkdir(parents=True, exist_ok=True)
