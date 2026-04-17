from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from authentication_service.app.api.v1.routers import router as api_router
from authentication_service.app.core.db import engine, Base

import authentication_service.app.models  # noqa

app = FastAPI(title="authentication_service", version="1.0")
app.include_router(api_router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    openapi_schema["servers"] = [
        {"url": "/authentication", "description": "Gateway mount"}
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
    # Create tables in development. Use Alembic migrations in production.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
