import httpx

from authentication_service.app.core.config import settings
from authentication_service.app.core.custom_loggers import get_file_logger

logger = get_file_logger(
    name="auth_email_client",
    prefix="auth_email_client"
)


async def send_email(to: list[str], subject: str, body: str, html: bool = False) -> None:
    endpoint = f"{settings.EMAIL_SERVICE_URL.rstrip('/')}/send"
    payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "html": html,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
        logger.info("Sent email to %s with subject=%s", to, subject)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
