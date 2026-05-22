"""One-time script to obtain a Google Drive OAuth refresh token.

Run locally (requires google-auth-oauthlib):
    pip install google-auth-oauthlib
    python scripts/get_drive_token.py

A browser window opens for Google sign-in. After authorising, the refresh
token is printed to stdout — paste it into Railway as GOOGLE_REFRESH_TOKEN.

Prerequisites:
- GCP project with Drive API enabled
- OAuth 2.0 Client ID of type "Desktop app" created in GCP Console
- OAuth consent screen configured (add your Google account as a test user
  while in Testing mode, or publish to Production to remove the 7-day expiry)
"""

from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def main() -> None:
    """Run the OAuth flow and print the refresh token to stdout."""
    client_id = input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = input("GOOGLE_CLIENT_SECRET: ").strip()

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": _TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=_SCOPES,
    )
    creds = flow.run_local_server(port=0)

    print("\n--- Copy the value below into Railway ---")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("-----------------------------------------\n")
    print("Also set in Railway:")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print("\nThen remove GOOGLE_SERVICE_ACCOUNT_JSON from Railway Variables.")


if __name__ == "__main__":
    main()
