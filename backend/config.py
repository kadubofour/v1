"""Server settings, read from environment variables or a `.env` file next to serve.py."""
import os
import secrets
from dataclasses import dataclass, field


def load_dotenv(path):
    """Minimal .env reader: KEY=value lines, # comments, optional quotes. Real env vars win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


@dataclass
class Config:
    admin_password: str = ""
    data_dir: str = "data"
    outbox_dir: str = "outbox"
    site_url: str = "http://localhost:5510"
    mail_from: str = "Nyon Derma <hello@nyonderma.com>"
    reply_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"  # starttls | ssl | none
    rate_limit_per_minute: int = 5
    generated_password: bool = field(default=False, repr=False)

    @property
    def email_enabled(self):
        return bool(self.smtp_host)

    @classmethod
    def from_env(cls, root, default_port):
        load_dotenv(os.path.join(root, ".env"))
        env = os.environ.get
        cfg = cls(
            admin_password=env("ADMIN_PASSWORD", ""),
            data_dir=os.path.join(root, env("DATA_DIR", "data")),
            outbox_dir=os.path.join(root, env("OUTBOX_DIR", "outbox")),
            site_url=env("SITE_URL", f"http://localhost:{default_port}").rstrip("/"),
            mail_from=env("MAIL_FROM", "Nyon Derma <hello@nyonderma.com>"),
            reply_to=env("REPLY_TO", ""),
            smtp_host=env("SMTP_HOST", ""),
            smtp_port=int(env("SMTP_PORT", "587")),
            smtp_user=env("SMTP_USER", ""),
            smtp_password=env("SMTP_PASSWORD", ""),
            smtp_security=env("SMTP_SECURITY", "starttls").lower(),
            rate_limit_per_minute=int(env("RATE_LIMIT_PER_MINUTE", "5")),
        )
        if not cfg.admin_password:
            # Never fall back to a guessable default: make a one-off password and print it at startup.
            cfg.admin_password = secrets.token_urlsafe(9)
            cfg.generated_password = True
        return cfg
