import httpx

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import settings


class EmailClient:
    def __init__(self):
        self.base_url = (settings.EMAIL_SERVICE_URL or "").strip()
        self.timeout = settings.EMAIL_SEND_TIMEOUT_SECONDS

    async def send_email(self, *, to: list[str], subject: str, body: str, html: bool = False) -> None:
        if not self.base_url:
            raise BusinessException(message="EMAIL_SERVICE_URL is not configured", status_code=500)

        if not to:
            return

        payload = {
            "to": to,
            "subject": subject,
            "body": body,
            "html": html,
        }

        url = f"{self.base_url.rstrip('/')}/send"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise BusinessException(
                    message=f"Failed to send email notification: {str(exc)}",
                    status_code=502,
                ) from exc
