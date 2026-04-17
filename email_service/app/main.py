from fastapi import FastAPI
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
def send_email_api(payload: EmailRequest):
    send_email(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        html=payload.html
    )
    return {"status": "sent"}
