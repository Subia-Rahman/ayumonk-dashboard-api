from http.client import HTTPException
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.exceptions import http_exception_handler, validation_exception_handler, unhandled_exception_handler,business_exception_handler
from config_service.app.core.logging import setup_logging
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from config_service.app.api.v1 import routes
from config_service.app.core.db import engine, Base
import asyncio
from config_service.app.core.audit import events
from fastapi.exceptions import RequestValidationError
from config_service.app.models import *

def create_app():
    app = FastAPI(title="config_service", docs_url=None, redoc_url=None)
    app.include_router(routes.router)
    return app

setup_logging()

app = create_app()

# Register handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(BusinessException, business_exception_handler)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
        <title>config_service - Swagger UI</title>
        <style>
            .login-panel {{
                display: flex;
                gap: 8px;
                padding: 12px 16px;
                border-bottom: 1px solid #e5e7eb;
                align-items: center;
                background: #fafafa;
            }}
            .login-panel input {{
                padding: 6px 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                font-size: 14px;
            }}
            .login-panel button {{
                padding: 6px 12px;
                border: none;
                border-radius: 4px;
                background: #2563eb;
                color: white;
                cursor: pointer;
            }}
            .login-panel .status {{
                font-size: 13px;
                color: #374151;
            }}
        </style>
    </head>
    <body>
        <div class="login-panel">
            <strong>Login:</strong>
            <input id="sw-username" type="text" placeholder="username" />
            <input id="sw-password" type="password" placeholder="password" />
            <button id="sw-login">Get Token</button>
            <span class="status" id="sw-status"></span>
        </div>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
        <script>
        const openapiUrl = window.location.pathname.replace(/\\/docs$/, "/openapi.json");
        const ui = SwaggerUIBundle({{
            url: openapiUrl,
            dom_id: '#swagger-ui',
            presets: [
                SwaggerUIBundle.presets.apis,
                SwaggerUIStandalonePreset
            ],
            layout: "BaseLayout",
            persistAuthorization: true
        }});

        async function loginAndAuthorize() {{
            const username = document.getElementById("sw-username").value;
            const password = document.getElementById("sw-password").value;
            const statusEl = document.getElementById("sw-status");
            statusEl.textContent = "Authenticating...";

            const body = new URLSearchParams();
            body.append("username", username);
            body.append("password", password);

            try {{
                const res = await fetch("/authentication/api/v1/auth/token", {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/x-www-form-urlencoded"
                    }},
                    body: body.toString()
                }});
                if (!res.ok) {{
                    const errText = await res.text();
                    statusEl.textContent = "Login failed";
                    console.error("Login failed:", errText);
                    return;
                }}
                const data = await res.json();
                let token = data.access_token || "";
                if (token.toLowerCase().startsWith("bearer ")) {{
                    token = token.slice(7);
                }}
                if (!token) {{
                    statusEl.textContent = "No token returned";
                    return;
                }}
                ui.preauthorizeApiKey("BearerAuth", token);
                statusEl.textContent = "Authorized";
            }} catch (err) {{
                console.error(err);
                statusEl.textContent = "Login error";
            }}
        }}

        document.getElementById("sw-login").addEventListener("click", loginAndAuthorize);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version="1.0",
        routes=app.routes,
    )
    openapi_schema["servers"] = [
        {"url": "/config", "description": "Local gateway"},
    ]
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    # Remove OAuth2 password flow from docs to avoid client_id/client_secret fields.
    oauth2_keys = [
        key for key, value in security_schemes.items()
        if isinstance(value, dict) and value.get("type") == "oauth2"
    ]
    for key in oauth2_keys:
        security_schemes.pop(key, None)
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    # Remove OAuth2 security requirements from operations
    for path in openapi_schema.get("paths", {}).values():
        for op in path.values():
            if isinstance(op, dict) and "security" in op:
                op["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

@app.on_event("startup")
async def startup():
    print("Tables seen by SQLAlchemy:", Base.metadata.tables.keys())
    # in dev we create tables automatically; use alembic in prod
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
