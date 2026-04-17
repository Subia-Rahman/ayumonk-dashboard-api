# config-service

Starter service following the microservice pattern.

## Google OAuth refresh token utility

Use this once to generate `GOOGLE_FORMS_REFRESH_TOKEN` for personal Gmail OAuth user mode.

```powershell
.\venv\Scripts\python.exe config_service\generate_token.py `
  --client-secrets-file "D:\path\oauth_client_secret.json" `
  --env-file ".env"
```

Notes:
- The script requests scopes for Forms + Drive + Apps Script provisioning.
- `--env-file` is optional. Without it, the script prints env keys to copy.

## Google Form -> Webhook integration

Configure in `.env`:

```env
GOOGLE_FORMS_WEBHOOK_URL=https://your-ngrok-domain.ngrok-free.dev/config/api/v1/employee_forms/webhook
GOOGLE_FORMS_EMAIL_QUESTION_TITLE=Email
EMPLOYEE_FORM_WEBHOOK_SECRET=your_long_random_secret
```

Behavior:
- `POST /api/v1/sessions/{session_id}/generate-google-form` now:
  - creates Google Form
  - creates/updates form-bound Apps Script
  - injects `company_id` from session
  - injects generated `form_id`
  - creates `onFormSubmit` trigger automatically
- No manual Apps Script editing is required.

Supported payload formats:
- Legacy internal payload:
  - `{"company_id","form_id","form_data": {...}}`
- Google webhook payload:
  - `{"company_id","form_id","response_id","respondent_email","submitted_at","answers": {...}}`

Webhook security:
- Auto-provisioned Apps Script sends `X-Webhook-Secret`.
- If `EMPLOYEE_FORM_WEBHOOK_SECRET` is set, missing/wrong secret is rejected with `401`.
