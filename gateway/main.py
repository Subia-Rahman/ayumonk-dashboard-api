from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from authentication_service.app.main import app as authentication_app
from config_service.app.main import app as config_app
from email_service.app.main import app as email_app


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Propagate startup/shutdown to mounted sub-apps.

    FastAPI's `Mount` does not run a sub-app's lifespan automatically, so
    handlers like config_service's APScheduler bootstrap and create_all are
    skipped when the gateway is the entrypoint. Delegating to each sub-app's
    lifespan_context restores that behavior.
    """
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(
            config_app.router.lifespan_context(config_app)
        )
        await stack.enter_async_context(
            authentication_app.router.lifespan_context(authentication_app)
        )
        await stack.enter_async_context(
            email_app.router.lifespan_context(email_app)
        )
        yield


app = FastAPI(title="API Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*","https://grades-assets-civilization-optional.trycloudflare.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/config", config_app)
app.mount("/authentication", authentication_app)
app.mount("/email", email_app)
