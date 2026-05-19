import asyncio
from typing import Optional

import httpx

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import settings
from config_service.app.core.custom_loggers import get_file_logger


logger = get_file_logger(name="email_client", prefix="email_client")


_shared_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client(timeout: float) -> httpx.AsyncClient:
    """Lazily create a single shared httpx.AsyncClient so we keep HTTP/keep-alive
    connections to email_service instead of opening a new TCP/TLS connection
    per email (which used to happen because the client was created with
    `async with` per call)."""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=40,
                keepalive_expiry=30.0,
            ),
        )
    return _shared_http_client


async def aclose_email_client() -> None:
    """Optional teardown hook for app shutdown. Not strictly required — the
    client is process-scoped and will release on interpreter exit."""
    global _shared_http_client
    if _shared_http_client and not _shared_http_client.is_closed:
        await _shared_http_client.aclose()
    _shared_http_client = None


class EmailClient:
    """Send transactional email.

    Default transport (`EMAIL_USE_HTTP_TRANSPORT=False`) calls
    `email_service.smtp_client.send_email` directly in the current process
    via `asyncio.to_thread`. This avoids a same-process HTTP loopback hop
    when all sub-apps are mounted on the same gateway — the original cause
    of the reminder dispatcher freezing the event loop.

    Set `EMAIL_USE_HTTP_TRANSPORT=True` and `EMAIL_SERVICE_URL=<host>` when
    email_service is deployed as a separate process / container.
    """

    def __init__(self):
        self.base_url = (settings.EMAIL_SERVICE_URL or "").strip()
        self.timeout = settings.EMAIL_SEND_TIMEOUT_SECONDS
        self.use_http = bool(getattr(settings, "EMAIL_USE_HTTP_TRANSPORT", False))

    async def send_email(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        html: bool = False,
    ) -> None:
        if not to:
            return

        if self.use_http:
            await self._send_via_http(to=to, subject=subject, body=body, html=html)
        else:
            await self._send_in_process(to=to, subject=subject, body=body, html=html)

    async def _send_in_process(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        html: bool,
    ) -> None:
        # Import lazily so config_service can boot without email_service on
        # the path (e.g. in tests).
        try:
            from email_service.app.smtp_client import send_email as smtp_send
        except ImportError as exc:
            raise BusinessException(
                message="email_service is not available in-process",
                status_code=500,
            ) from exc

        try:
            await asyncio.to_thread(smtp_send, to, subject, body, html)
        except Exception as exc:
            logger.warning("In-process SMTP send failed: %s", exc)
            raise BusinessException(
                message=f"Failed to send email notification: {exc}",
                status_code=502,
            ) from exc

    async def _send_via_http(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        html: bool,
    ) -> None:
        if not self.base_url:
            raise BusinessException(
                message="EMAIL_SERVICE_URL is not configured",
                status_code=500,
            )

        url = f"{self.base_url.rstrip('/')}/send"
        payload = {"to": to, "subject": subject, "body": body, "html": html}
        client = _get_http_client(self.timeout)

        try:
            response = await client.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("HTTP email send to %s failed: %s", url, exc)
            raise BusinessException(
                message=f"Failed to send email notification: {exc}",
                status_code=502,
            ) from exc
