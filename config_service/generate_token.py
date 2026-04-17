import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.scripts",
    "https://www.googleapis.com/auth/script.projects",
    "https://www.googleapis.com/auth/script.deployments",
    "https://www.googleapis.com/auth/script.scriptapp",
]


def upsert_env_file(env_file: Path, values: dict[str, str]) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    output = []
    seen = set()
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            output.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)

    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")

    env_file.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OAuth refresh token for Google Forms + Apps Script.")
    parser.add_argument(
        "--client-secrets-file",
        default="config_service/client_secret.json",
        help="Path to OAuth client JSON from Google Cloud.",
    )
    parser.add_argument("--port", type=int, default=5000, help="Local callback port.")
    parser.add_argument("--env-file", default=None, help="Optional .env file to update.")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser.")
    args = parser.parse_args()

    client_secrets_file = Path(args.client_secrets_file).resolve()
    if not client_secrets_file.exists():
        raise FileNotFoundError(f"Client secrets file not found: {client_secrets_file}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), scopes=SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=args.port,
        open_browser=not args.no_browser,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Open this URL in your browser:\n{url}",
        success_message="Authentication complete. You can close this tab.",
    )

    if not creds.refresh_token:
        raise RuntimeError(
            "No refresh token received. Revoke old app access in Google Account and run again."
        )

    env_values = {
        "GOOGLE_FORMS_CLIENT_ID": creds.client_id,
        "GOOGLE_FORMS_CLIENT_SECRET": creds.client_secret,
        "GOOGLE_FORMS_REFRESH_TOKEN": creds.refresh_token,
        "GOOGLE_FORMS_TOKEN_URI": creds.token_uri or "https://oauth2.googleapis.com/token",
    }

    print("\nGenerated credentials:\n")
    for key, value in env_values.items():
        print(f"{key}={value}")

    if args.env_file:
        env_file = Path(args.env_file).resolve()
        upsert_env_file(env_file, env_values)
        print(f"\nUpdated env file: {env_file}")


if __name__ == "__main__":
    main()
