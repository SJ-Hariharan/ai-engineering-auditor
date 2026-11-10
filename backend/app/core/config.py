"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDITOR_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://localhost/auditor"
    redis_url: str = "redis://localhost:6379/0"
    # Run audit jobs in-process instead of via RQ (tests / single-process dev).
    inline_jobs: bool = False

    # Where repository workspaces live. Must not be inside the web root.
    workspace_root: Path = Path("./var/workspaces")
    workspace_ttl_hours: int = 24

    # Upload and repository limits (defence against zip bombs / huge repos).
    max_upload_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 300 * 1024 * 1024
    max_files: int = 20_000
    max_file_bytes_analyzed: int = 1 * 1024 * 1024
    clone_timeout_seconds: int = 120
    # Per-user limits (SEC-06)
    max_active_audits_per_user: int = 2
    max_audits_per_user_per_day: int = 50

    # Scanner behaviour
    scanner_timeout_seconds: int = 300
    offline: bool = False  # disables OSV-Scanner/Trivy DB lookups and Semgrep registry packs
    semgrep_extra_configs: list[str] = Field(default_factory=list)
    # Trivy scanners. "misconfig" needs only a small checks bundle; adding "vuln" downloads a
    # ~1.6 GB vulnerability DB and duplicates OSV-Scanner (results are de-duplicated).
    trivy_scanners: str = Field(default="misconfig", pattern=r"^(misconfig|vuln|vuln,misconfig|misconfig,vuln)$")

    # Sandbox (test execution)
    sandbox_enabled: bool = False  # opt-in: needs Docker access; read SECURITY.md first
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_pids: int = 256
    sandbox_timeout_seconds: int = 300
    sandbox_python_image: str = "python:3.12-slim"
    sandbox_node_image: str = "node:22-slim"
    # Optional hardened OCI runtime, e.g. "runsc" (gVisor). Empty = Docker default (runc).
    sandbox_runtime: str = ""

    # Auth
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False  # set True behind HTTPS
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    allow_registration: bool = True
    # Signs login "device cookies" (SEC-02). Required in production; random per process otherwise.
    secret_key: str = ""

    # LLM (optional). Keys come from the server environment only.
    llm_provider: str = "anthropic"  # "anthropic" | "openai" | "none"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5"
    llm_timeout_seconds: int = 90
    llm_max_input_chars: int = 60_000

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @model_validator(mode="after")
    def _reject_unsafe_production(self) -> "Settings":
        """SEC-07: fail at startup instead of silently running production with dev settings."""
        if self.is_production:
            bad = []
            if not self.cookie_secure:
                bad.append("AUDITOR_COOKIE_SECURE must be true (session cookies over HTTPS only)")
            if self.inline_jobs:
                bad.append("AUDITOR_INLINE_JOBS must be false (audits must run in the worker)")
            if len(self.secret_key) < 32 or "CHANGE-ME" in self.secret_key:
                bad.append("AUDITOR_SECRET_KEY must be set to a random string of at least 32 characters")
            if bad:
                raise ValueError("Unsafe production configuration: " + "; ".join(bad))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
