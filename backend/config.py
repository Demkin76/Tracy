from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POA_", env_file=".env", extra="ignore")

    admin_token: SecretStr | None = None  # Legacy configuration only; never accepted for authentication.
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
