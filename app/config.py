"""All settings come from environment variables (or a local .env file).

Secrets (SESSION_SECRET, SMTP_PASSWORD) and anything that identifies the real employer
(PLANNING_EMAIL) are never committed: in the cluster they come from OpenBao.
"""

from functools import lru_cache
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Ruilingen"
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./ruilingen.db"
    timezone: str = "Europe/Amsterdam"

    # Signs the session cookie. Changing it logs everyone out.
    session_secret: str = "dev-only-change-me"
    # Rolling: every visit renews it. People without an email can't log back in on their own,
    # so keep this long.
    session_days: int = 365
    login_link_minutes: int = 20
    # Max login mails per address per hour (stops someone flooding a colleague's inbox).
    login_mails_per_hour: int = 5

    # Comma separated. These addresses are made admin at startup (and created if missing).
    admin_emails: str = ""
    planning_email: str = "planning@example.org"

    # "smtp" sends mail (Brevo, Resend, ... all speak SMTP). "console" only prints it to the log
    # (development). "none": no mail at all; email login and notifications are hidden.
    mail_backend: str = "none"
    mail_from: str = "Ruilingen <noreply@ruilingen.app>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Shows the login link on screen instead of only mailing it. Local development only.
    dev_mode: bool = False

    # Roosters are published on this weekday (0 = monday, 1 = tuesday) for the week after.
    # The day filter offers dates up to the end of the latest published rooster.
    roster_release_weekday: int = 1

    # Swaps, listings and notifications older than this (by shift date) are deleted.
    retention_days: int = 42

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        host = urlparse(self.base_url).hostname or ""
        local = host in {"localhost", "127.0.0.1", "testserver"} or host.endswith(".localhost")
        if not local:
            if self.dev_mode:
                raise ValueError("DEV_MODE is only allowed when BASE_URL is localhost")
            if self.session_secret == "dev-only-change-me" or len(self.session_secret) < 32:
                raise ValueError("Set SESSION_SECRET to a random value of at least 32 characters")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def mail_enabled(self) -> bool:
        return (self.mail_backend == "smtp" and bool(self.smtp_host)) or (
            self.mail_backend == "console" and self.dev_mode
        )

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
