from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config_service.app.main import app as config_app
from authentication_service.app.main import app as authentication_app
from email_service.app.main import app as email_app
app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/config", config_app)
app.mount("/authentication", authentication_app)
app.mount("/email", email_app)