from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POA_", env_file=".env", extra="ignore")

    copilot_provider: Literal["auto", "gemini", "openai", "reference"] = "auto"
    gemini_api_key: SecretStr | None = None
    gemini_api_key_2: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.1-flash-lite", pattern=r"^gemini-[a-zA-Z0-9._-]+$")
    copilot_api_key: SecretStr | None = None
    copilot_model: str = "gpt-4o-mini"

    admin_token: SecretStr | None = None  # Legacy configuration only; never accepted for authentication.
    environment: Literal["development", "production"] = "development"
    frontend_only: bool = False
    origin_proxy_token: SecretStr | None = None
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    signup_enabled: bool = True
    devnet_enabled: bool = True
    adaptive_devnet_anchors_enabled: bool = False
    adaptive_devnet_payments_enabled: bool = False
    adaptive_devnet_dex_enabled: bool = False
    signing_seed: SecretStr
    execution_wallet_seed: SecretStr
    control_credentials_path: Path = Path("data/control-credentials.json")
    control_resources_path: Path = Path("data/control-resources.json")
    reconciler_enabled: bool = True
    reconciliation_interval_seconds: float = Field(default=5, ge=0.05, le=300)
    owner_daily_lamports: int = Field(default=1_000_000_000, ge=1)
    platform_daily_lamports: int = Field(default=5_000_000_000, ge=1)
    execution_enabled: bool = True
    session_seconds: int = Field(default=604800, ge=60, le=2592000)
    cookie_secure: bool = False
    database_path: Path = Path("data/poa.sqlite3")
    rpc_url: str = "https://api.devnet.solana.com"
    verification_rpc_url: str = "https://api.devnet.solana.com"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    request_max_age_seconds: int = Field(default=300, ge=1)
    request_future_skew_seconds: int = Field(default=30, ge=0)
    verification_attempts: int = Field(default=8, ge=1, le=30)
    verification_interval_seconds: float = Field(default=1.5, ge=0, le=10)

    @field_validator("rpc_url", "verification_rpc_url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Only HTTPS Devnet RPC endpoints are supported")
        return value

    @model_validator(mode="after")
    def production_settings(self):
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("Production requires secure cookies and HTTPS")
            if not self.allowed_hosts or any(h == "*" or h == "testserver" for h in self.allowed_hosts):
                raise ValueError("Set explicit production allowed hosts")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS")
            if self.devnet_enabled:
                raise ValueError("Disable Devnet execution for the paper MVP")
        return self
