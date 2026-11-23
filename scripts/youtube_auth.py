"""One-time: get a YouTube refresh token for the pipeline (run on your laptop, it opens a browser).

Before running:
  1. Google Cloud console -> new project -> enable "YouTube Data API v3".
  2. OAuth consent screen: External, add yourself as a test user, then click "Publish app"
     (status "In production"). Refresh tokens from apps left in "Testing" expire after 7 days.
  3. Credentials -> Create OAuth client ID -> "Desktop app" -> download JSON as client_secret.json.

  pip install google-auth-oauthlib
  python scripts/youtube_auth.py client_secret.json
  aws ssm put-parameter --overwrite --type SecureString --name /yt-autopilot/youtube-oauth --value file://youtube_oauth.json

Remember: until your project passes the YouTube API audit, API uploads are locked to private.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    out = {"client_id": creds.client_id, "client_secret": creds.client_secret, "refresh_token": creds.refresh_token}
    with open("youtube_oauth.json", "w") as f:
        json.dump(out, f)
    print("Wrote youtube_oauth.json - store it in SSM Parameter Store, then delete the local file.")


if __name__ == "__main__":
    main()
