import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from email_service.app.schemas import EmailRequest
from email_service.app.smtp_client import send_email

app = FastAPI(title="Email Module APIs")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version="1.0",
        routes=app.routes,
    )
    openapi_schema["servers"] = [
        {"url": "/email", "description": "Gateway mount"}
    ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.post("/send")
async def send_email_api(payload: EmailRequest):
    """Run the blocking SMTP send on the threadpool so the event loop stays
    free to serve other requests. FastAPI would do this automatically for a
    `def` endpoint, but making it explicit keeps the contract clear and lets
    us surface SMTP errors as 502 instead of a generic 500.
    """
    try:
        await asyncio.to_thread(
            send_email,
            payload.to,
            payload.subject,
            payload.body,
            payload.html,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP send failed: {exc}") from exc

    return {"status": "sent"}
