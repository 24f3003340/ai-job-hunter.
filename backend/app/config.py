from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_ENVS = {"development", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBHUNTER_", env_file=".env", extra="ignore")

    env: str = "development"  # development | test | production
    database_url: str = "sqlite:///./jobhunter.db"
    public_base_url: str = "http://localhost:5173"  # used in e-mailed links
    cors_origins: list[str] = ["http://localhost:5173"]

    # sessions / auth
    session_ttl_hours: int = 24 * 7
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    password_reset_ttl_minutes: int = 30
    email_verify_ttl_hours: int = 24
    reset_requests_per_hour: int = 3  # per account
    verify_resends_per_hour: int = 3  # per account
    verify_resend_cooldown_seconds: int = 60
    require_verified_email: bool = False  # gate approve/submit/AI features; forced on in production

    # rate limiting (in-process sliding window; see README for multi-process caveat)
    rate_limit_enabled: bool = True
    rate_limit_default: str = "300/minute"  # per client IP, all endpoints
    rate_limit_auth: str = "10/minute"  # login/register/reset/verify, per client IP
    rate_limit_upload: str = "10/hour"  # per authenticated user
    rate_limit_generate: str = "20/hour"  # resume generation, per user
    trust_proxy_headers: bool = False  # honour X-Forwarded-For only behind a trusted proxy

    # e-mail
    email_backend: str = "console"  # console | smtp | outbox (tests)
    email_from: str = "no-reply@example.invalid"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # uploads
    storage_dir: Path = Path("./var/storage")
    max_upload_bytes: int = 5 * 1024 * 1024
    allowed_upload_types: list[str] = ["pdf", "docx"]
    max_pdf_pages: int = 30
    max_docx_uncompressed_bytes: int = 30 * 1024 * 1024
    clamav_host: str = ""  # empty => malware scanning NOT configured
    clamav_port: int = 3310
    require_malware_scan: bool = False  # forced on in production unless allow_unscanned_uploads
    allow_unscanned_uploads: bool = False

    # AI provider
    ai_provider: str = "rule_based"  # rule_based (local, no data leaves the server) | anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    ai_timeout_seconds: float = 60.0

    @model_validator(mode="after")
    def _production_checks(self):
        if self.env in _DEV_ENVS:
            return self
        problems: list[str] = []
        if self.env != "production":
            problems.append(f"JOBHUNTER_ENV must be development, test or production (got {self.env!r})")
        if self.database_url.startswith("sqlite"):
            problems.append("JOBHUNTER_DATABASE_URL must point at PostgreSQL in production")
        if not self.public_base_url.startswith("https://"):
            problems.append("JOBHUNTER_PUBLIC_BASE_URL must be https:// in production")
        if any(o == "*" or o.startswith("http://") for o in self.cors_origins):
            problems.append("JOBHUNTER_CORS_ORIGINS must be explicit https origins in production")
        if self.email_backend not in ("smtp",) or not self.smtp_host:
            problems.append("production requires JOBHUNTER_EMAIL_BACKEND=smtp with JOBHUNTER_SMTP_HOST set")
        if not self.require_verified_email:
            problems.append("JOBHUNTER_REQUIRE_VERIFIED_EMAIL must be true in production")
        if not self.rate_limit_enabled:
            problems.append("rate limiting cannot be disabled in production")
        if not self.clamav_host and not self.allow_unscanned_uploads:
            problems.append("configure JOBHUNTER_CLAMAV_HOST or explicitly set JOBHUNTER_ALLOW_UNSCANNED_UPLOADS=true")
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("JOBHUNTER_ANTHROPIC_API_KEY is required when ai_provider=anthropic")
        if problems:
            raise ValueError("Unsafe production configuration:\n- " + "\n- ".join(problems))
        return self


settings = Settings()
