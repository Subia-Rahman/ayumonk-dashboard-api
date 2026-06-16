from __future__ import annotations
from typing import Any
import json

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import settings

try:
    from google.auth.transport.requests import Request
    from google.oauth2 import credentials as oauth_credentials
    from google.oauth2 import service_account
    from googleapiclient.errors import HttpError
    from googleapiclient.discovery import build
except ImportError:
    Request = None
    oauth_credentials = None
    service_account = None
    HttpError = None
    build = None


class GoogleFormGenerationService:
    REQUIRED_SCOPES = (
        "https://www.googleapis.com/auth/forms.body",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.scripts",
        "https://www.googleapis.com/auth/script.projects",
        "https://www.googleapis.com/auth/script.deployments",
        "https://www.googleapis.com/auth/script.scriptapp",
        "https://www.googleapis.com/auth/script.external_request"
    )

    def __init__(self):
        self.credentials_file = self._clean(settings.GOOGLE_FORMS_CREDENTIALS_FILE)
        self.delegated_user = self._clean(settings.GOOGLE_FORMS_DELEGATED_USER)
        self.title_prefix = settings.GOOGLE_FORMS_TITLE_PREFIX

        self.oauth_client_id = self._clean(settings.GOOGLE_FORMS_CLIENT_ID)
        self.oauth_client_secret = self._clean(settings.GOOGLE_FORMS_CLIENT_SECRET)
        self.oauth_refresh_token = self._clean(settings.GOOGLE_FORMS_REFRESH_TOKEN)
        self.oauth_token_uri = self._clean(settings.GOOGLE_FORMS_TOKEN_URI) or "https://oauth2.googleapis.com/token"
        self.webhook_url = self._clean(settings.GOOGLE_FORMS_WEBHOOK_URL)
        self.webhook_secret = self._clean(settings.EMPLOYEE_FORM_WEBHOOK_SECRET)
        self.email_question_title = settings.GOOGLE_FORMS_EMAIL_QUESTION_TITLE

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def _validate_dependencies(self) -> None:
        if service_account is None or build is None or oauth_credentials is None or Request is None:
            raise BusinessException(
                message="Google API dependencies are missing. Install google-api-python-client and google-auth.",
                status_code=500,
            )

    def _has_oauth_user_config(self) -> bool:
        return bool(
            self.oauth_client_id
            and self.oauth_client_secret
            and self.oauth_refresh_token
        )

    def _build_oauth_user_credentials(self):
        credentials = oauth_credentials.Credentials(
            token=None,
            refresh_token=self.oauth_refresh_token,
            token_uri=self.oauth_token_uri,
            client_id=self.oauth_client_id,
            client_secret=self.oauth_client_secret,
        )
        # Refresh early to fail fast on invalid credentials.
        credentials.refresh(Request())
        return credentials

    def _build_credentials(self):
        if self._has_oauth_user_config():
            return self._build_oauth_user_credentials()

        if not self.credentials_file:
            raise BusinessException(
                message=(
                    "Google credentials are not configured. Provide OAuth user credentials "
                    "(GOOGLE_FORMS_CLIENT_ID, GOOGLE_FORMS_CLIENT_SECRET, GOOGLE_FORMS_REFRESH_TOKEN) "
                    "or service account file (GOOGLE_FORMS_CREDENTIALS_FILE)."
                ),
                status_code=500,
            )

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file,
            scopes=self.REQUIRED_SCOPES,
        )
        if self.delegated_user:
            credentials = credentials.with_subject(self.delegated_user)
        return credentials

    def _build_apps_script_files(
        self,
        *,
        form_id: str,
        company_id: str,
    ) -> list[dict[str, str]]:
        if not self.webhook_url:
            raise BusinessException(
                message="GOOGLE_FORMS_WEBHOOK_URL is required to provision the Google Form webhook script.",
                status_code=500,
            )

        config_block = {
            "webhookUrl": self.webhook_url,
            "webhookSecret": self.webhook_secret or "",
            "companyId": company_id,
            "formId": form_id,
            "emailQuestionTitle": self.email_question_title,
        }

        code_source = f"""const CONFIG = {json.dumps(config_block, indent=2)};

function onFormSubmitHandler(e) {{
  const itemResponses = e.response.getItemResponses();
  const answers = {{}};
  let respondentEmail = "";

  for (let i = 0; i < itemResponses.length; i++) {{
    const itemResponse = itemResponses[i];
    const questionTitle = itemResponse.getItem().getTitle();
    const answer = normalizeAnswer(itemResponse.getResponse());
    answers[questionTitle] = answer;
    if (questionTitle === CONFIG.emailQuestionTitle) {{
      respondentEmail = answer;
    }}
  }}

  if (!respondentEmail && typeof e.response.getRespondentEmail === "function") {{
    respondentEmail = e.response.getRespondentEmail() || "";
  }}

  const payload = {{
    company_id: CONFIG.companyId,
    form_id: CONFIG.formId,
    response_id: e.response.getId(),
    respondent_email: respondentEmail,
    submitted_at: e.response.getTimestamp().toISOString(),
    answers: answers
  }};

  const headers = {{"Content-Type": "application/json"}};
  if (CONFIG.webhookSecret) {{
    headers["X-Webhook-Secret"] = CONFIG.webhookSecret;
  }}

  const options = {{
    method: "post",
    headers: headers,
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  }};

  const res = UrlFetchApp.fetch(CONFIG.webhookUrl, options);
  const code = res.getResponseCode();
  if (code < 200 || code >= 300) {{
    Logger.log("Webhook error. status=%s body=%s", code, res.getContentText());
  }}
}}

function setupTrigger() {{
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {{
    if (triggers[i].getHandlerFunction() === "onFormSubmitHandler") {{
      ScriptApp.deleteTrigger(triggers[i]);
    }}
  }}

  ScriptApp.newTrigger("onFormSubmitHandler")
    .forForm(FormApp.getActiveForm())
    .onFormSubmit()
    .create();
}}

function normalizeAnswer(value) {{
  if (Array.isArray(value)) {{
    return value.join(", ");
  }}
  if (value === null || value === undefined) {{
    return "";
  }}
  return String(value);
}}
"""

        manifest_source = json.dumps(
            {
                "timeZone": "UTC",
                "runtimeVersion": "V8",
                "exceptionLogging": "STACKDRIVER",
                "executionApi": {"access": "MYSELF"},
                "oauthScopes": [
                    "https://www.googleapis.com/auth/script.external_request",
                    "https://www.googleapis.com/auth/script.scriptapp",
                    "https://www.googleapis.com/auth/forms.currentonly",
                ],
            },
            indent=2,
        )

        return [
            {
                "name": "Code",
                "type": "SERVER_JS",
                "source": code_source,
            },
            {
                "name": "appsscript",
                "type": "JSON",
                "source": manifest_source,
            },
        ]

    def provision_form_webhook_script(
        self,
        *,
        form_id: str,
        company_id: str,
        existing_script_id: str | None = None,
    ) -> str:
        try:
            self._validate_dependencies()
            credentials = self._build_credentials()
            script_service = build("script", "v1", credentials=credentials, cache_discovery=False)

            if existing_script_id:
                script_id = existing_script_id
            else:
                script_id = None
            if not script_id:
                project = script_service.projects().create(
                    body={
                        "title": f"Form Webhook - {form_id}",
                        "parentId": form_id,
                    }
                ).execute()
                script_id = project.get("scriptId")
                if not script_id:
                    raise BusinessException(
                        message="Failed to create bound Apps Script project for generated form.",
                        status_code=500,
                    )

            files = self._build_apps_script_files(form_id=form_id, company_id=company_id)
            script_service.projects().updateContent(
                scriptId=script_id,
                body={"files": files},
            ).execute()

            run_result = self._run_setup_trigger(script_service=script_service, script_id=script_id)
            if run_result.get("error"):
                raise BusinessException(
                    message=f"Failed to create on-submit trigger on bound script: {run_result['error']}",
                    status_code=500,
                )

            return script_id
        except HttpError as exc:
            detail = ""
            if getattr(exc, "reason", None):
                detail = str(exc.reason)
            elif getattr(exc, "error_details", None):
                detail = str(exc.error_details)
            raise BusinessException(
                message=f"Apps Script provisioning failed. {detail}".strip(),
                status_code=502,
            ) from exc

    def _run_setup_trigger(self, script_service, script_id: str) -> dict:
        try:
            return script_service.scripts().run(
                scriptId=script_id,
                body={
                    "function": "setupTrigger",
                    "devMode": True,
                },
            ).execute()
        except HttpError as exc:
            raw = str(exc).lower()
            if "requested entity was not found" not in raw:
                raise

            # For some projects, Execution API needs an explicit deployment first.
            version = script_service.projects().versions().create(
                scriptId=script_id,
                body={"description": "auto-version for trigger bootstrap"},
            ).execute()
            version_number = version.get("versionNumber")
            if not version_number:
                raise BusinessException(
                    message="Apps Script version creation failed before trigger setup.",
                    status_code=500,
                )

            script_service.projects().deployments().create(
                scriptId=script_id,
                body={
                    "deploymentConfig": {
                        "description": "auto-deployment for webhook trigger setup",
                        "manifestFileName": "appsscript",
                        "versionNumber": version_number,
                    }
                },
            ).execute()

            return script_service.scripts().run(
                scriptId=script_id,
                body={"function": "setupTrigger"},
            ).execute()

    def _build_form_requests(self, question_payload: list[dict[str, Any]]) -> list[dict]:
        requests: list[dict] = []
        for index, question in enumerate(question_payload):
            options = question.get("options", [])
            item = {
                "title": question["question_text"],
                "questionItem": {
                    "question": {
                        "required": True,
                    }
                },
            }

            if options:
                item["questionItem"]["question"]["choiceQuestion"] = {
                    "type": "RADIO",
                    "options": [{"value": opt} for opt in options],
                }
            else:
                item["questionItem"]["question"]["textQuestion"] = {"paragraph": False}

            requests.append(
                {
                    "createItem": {
                        "item": item,
                        "location": {"index": index},
                    }
                }
            )
        return requests

    def create_form(
        self,
        session_title: str,
        session_description: str | None,
        question_payload: list[dict[str, Any]],
    ) -> dict[str, str]:
        self._validate_dependencies()
        try:
            credentials = self._build_credentials()
            forms_service = build("forms", "v1", credentials=credentials, cache_discovery=False)

            create_body = {
                "info": {
                    "title": f"{self.title_prefix} - {session_title}",
                }
            }
            created_form = forms_service.forms().create(body=create_body).execute()
            form_id = created_form.get("formId")

            if not form_id:
                raise BusinessException(message="Google Form was created without a formId.", status_code=500)

            requests = []
            if session_description:
                requests.append(
                    {
                        "updateFormInfo": {
                            "info": {"description": session_description},
                            "updateMask": "description",
                        }
                    }
                )

            requests.extend(self._build_form_requests(question_payload))
            if requests:
                forms_service.forms().batchUpdate(
                    formId=form_id,
                    body={"requests": requests},
                ).execute()

            latest_form = forms_service.forms().get(formId=form_id).execute()
            responder_url = latest_form.get("responderUri")
            if not responder_url:
                raise BusinessException(
                    message="Google Form was created but responder URL is not available.",
                    status_code=500,
                )

            return {
                "form_id": form_id,
                "responder_url": responder_url,
            }
        except HttpError as exc:
            detail = ""
            if getattr(exc, "reason", None):
                detail = str(exc.reason)
            elif getattr(exc, "error_details", None):
                detail = str(exc.error_details)
            raise BusinessException(
                message=f"Google API request failed. {detail}".strip(),
                status_code=502,
            ) from exc
        except BusinessException:
            raise
        except Exception as exc:
            raise BusinessException(
                message=f"Google Form generation failed: {str(exc)}",
                status_code=500,
            ) from exc
