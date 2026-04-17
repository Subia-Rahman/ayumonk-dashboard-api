import os
from pathlib import Path
import smtplib
import time
from dataclasses import dataclass
from typing import Optional

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email_service.app.config import settings


@dataclass
class EmailConfig:
    provider: str
    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool
    use_ssl: bool


_CACHE: dict = {"config": None, "fetched_at": 0.0}
_ENV_LOADED = False


def _load_env_file() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        _ENV_LOADED = True
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    _ENV_LOADED = True


def _get_active_config() -> EmailConfig:
    now = time.time()
    if _CACHE["config"] and (now - _CACHE["fetched_at"] < settings.EMAIL_CONFIG_CACHE_SECONDS):
        return _CACHE["config"]

    _load_env_file()

    smtp_host = settings.SMTP_HOST or os.getenv("SMTP_HOST")
    smtp_port = settings.SMTP_PORT or os.getenv("SMTP_PORT")
    smtp_user = settings.SMTP_USER or os.getenv("SMTP_USER")
    smtp_pass = settings.SMTP_PASS or os.getenv("SMTP_PASS")
    from_email = settings.FROM_EMAIL or os.getenv("FROM_EMAIL")
    smtp_use_tls = settings.SMTP_USE_TLS if settings.SMTP_USE_TLS is not None else os.getenv("SMTP_USE_TLS", "true")
    smtp_use_ssl = settings.SMTP_USE_SSL if settings.SMTP_USE_SSL is not None else os.getenv("SMTP_USE_SSL", "false")

    if not (smtp_host and smtp_port and smtp_user and smtp_pass and from_email):
        raise RuntimeError("Email configuration is missing. Set SMTP_* env vars in email_service/app/.env.")

    config = EmailConfig(
        provider="SMTP",
        host=str(smtp_host),
        port=int(smtp_port),
        username=str(smtp_user),
        password=str(smtp_pass),
        from_email=str(from_email),
        use_tls=str(smtp_use_tls).lower() in ("1", "true", "yes", "on"),
        use_ssl=str(smtp_use_ssl).lower() in ("1", "true", "yes", "on"),
    )
    _CACHE["config"] = config
    _CACHE["fetched_at"] = now
    return config


def send_email(to, subject, body, html=False):
    print('BEFORE GET EMAIL')
    cfg = _get_active_config()
    print('AFTER GET EMAIL')
    print(cfg)
    msg = MIMEMultipart()
    msg["From"] = cfg.from_email
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    mime_type = "html" if html else "plain"
    msg.attach(MIMEText(body, mime_type))

    last_exc: Optional[Exception] = None
    for attempt in range(1, settings.EMAIL_SEND_MAX_RETRIES + 1):
        try:
            if cfg.use_ssl:
                server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20)
            else:
                server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
            if cfg.use_tls and not cfg.use_ssl:
                server.starttls()
            server.login(cfg.username, cfg.password)
            server.sendmail(cfg.from_email, to, msg.as_string())
            server.quit()
            return
        except Exception as exc:
            last_exc = exc
            try:
                server.quit()
            except Exception:
                pass
            if attempt < settings.EMAIL_SEND_MAX_RETRIES:
                time.sleep(settings.EMAIL_SEND_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"Email send failed after retries: {last_exc}") from last_exc
