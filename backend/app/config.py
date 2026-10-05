from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KA_", env_file="../.env", extra="ignore")
    env: str = "development"
    dev_auth: bool = False
    database_url: str = (
        "postgresql+psycopg://knowledge_app:local-runtime-only@127.0.0.1:55432/knowledge"
    )
    migration_url: str = (
        "postgresql+psycopg://knowledge_owner:local-owner-only@127.0.0.1:55432/knowledge"
    )
    origin: str = "http://127.0.0.1:5173"
    storage_dir: str = "../.data/objects"
    generation_mode: str = "evidence"
    generation_enabled: bool = True
    semantic_search: bool = False
    relevance_gate: str = "coverage"
    auth_rate_per_minute: int = 20
    query_rate_per_minute: int = 30
    upload_rate_per_minute: int = 20
    anthropic_api_key: str = ""
    model: str = "claude-haiku-4-5-20251001"
    daily_limit: int = 200
    user_daily_limit: int = 30
    workspace_daily_limit: int = 100
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    session_secret: str = "local-development-session-secret-only"

    @model_validator(mode="after")
    def validate_mode(self):
        if self.generation_mode not in {"evidence", "anthropic"}:
            raise ValueError("Unsupported generation mode")
        if self.relevance_gate not in {"coverage"}:
            raise ValueError("Unsupported relevance gate")
        if self.env == "production":
            if self.dev_auth or not self.origin.startswith("https://"):
                raise ValueError("Production requires HTTPS and forbids development login")
            if self.session_secret == "local-development-session-secret-only":
                raise ValueError("Production requires a unique session secret")
            if not self.oidc_discovery_url.startswith("https://"):
                raise ValueError("Production requires OIDC discovery over HTTPS")
            # External storage and parser isolation are not release-verified yet.
            raise ValueError("Production release gate is closed; see docs/release.md")
        if self.generation_mode == "anthropic" and not self.anthropic_api_key:
            raise ValueError("Live generation requires a provider key")
        return self


settings = Settings()
