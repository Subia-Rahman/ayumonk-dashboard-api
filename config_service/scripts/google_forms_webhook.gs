/**
 * Google Apps Script: Submit Google Form responses to config_service webhook.
 *
 * Deployment steps:
 * 1) Open your Google Form -> Extensions -> Apps Script.
 * 2) Paste this script.
 * 3) Set values in CONFIG.
 * 4) Create trigger: onFormSubmit -> Head -> From form -> On form submit.
 * 5) Authorize script when prompted.
 */

const CONFIG = {
  WEBHOOK_URL: "https://transmarginal-autumnal-kenny.ngrok-free.dev/config/api/v1/employee_forms/webhook",
  WEBHOOK_SECRET: "", // Must match EMPLOYEE_FORM_WEBHOOK_SECRET (if configured)
  COMPANY_ID: "", // UUID string expected by backend
  FORM_ID: "", // Google Form ID (from form URL)
  EMAIL_QUESTION_TITLE: "Email", // Exact question title used for respondent email
};

function onFormSubmit(e) {
  const itemResponses = e.response.getItemResponses();
  const answers = {};
  let respondentEmail = "";

  for (let i = 0; i < itemResponses.length; i++) {
    const itemResponse = itemResponses[i];
    const questionTitle = itemResponse.getItem().getTitle();
    const answer = normalizeAnswer(itemResponse.getResponse());
    answers[questionTitle] = answer;
    if (questionTitle === CONFIG.EMAIL_QUESTION_TITLE) {
      respondentEmail = answer;
    }
  }

  if (!respondentEmail && typeof e.response.getRespondentEmail === "function") {
    respondentEmail = e.response.getRespondentEmail() || "";
  }

  const payload = {
    company_id: CONFIG.COMPANY_ID,
    form_id: CONFIG.FORM_ID,
    response_id: e.response.getId(),
    respondent_email: respondentEmail,
    submitted_at: e.response.getTimestamp().toISOString(),
    answers: answers,
  };

  const headers = { "Content-Type": "application/json" };
  if (CONFIG.WEBHOOK_SECRET) {
    headers["X-Webhook-Secret"] = CONFIG.WEBHOOK_SECRET;
  }

  const options = {
    method: "post",
    headers: headers,
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const res = UrlFetchApp.fetch(CONFIG.WEBHOOK_URL, options);
  const code = res.getResponseCode();
  if (code < 200 || code >= 300) {
    Logger.log("Webhook error. status=%s body=%s", code, res.getContentText());
  }
}

function normalizeAnswer(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

