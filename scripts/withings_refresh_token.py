import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


TOKENS_PATH = Path("secrets/withings_tokens.json")


def main() -> None:
    load_dotenv()
    data = json.loads(TOKENS_PATH.read_text())
    client_id = data.get("client_id") or os.environ["WITHINGS_CLIENT_ID"]
    client_secret = data.get("consumer_secret") or os.environ["WITHINGS_CLIENT_SECRET"]
    refresh_token = data["refresh_token"]

    url = "https://wbsapi.withings.net/v2/oauth2"
    params = {
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    r = requests.post(url, data=params)
    j = r.json()
    body = j["body"]

    # Update and persist
    data.update({
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_in": body["expires_in"],
        "token_type": body.get("token_type", data.get("token_type", "Bearer")),
        "userid": int(body.get("userid", data.get("userid", 0))),
    })
    TOKENS_PATH.write_text(json.dumps(data, indent=2))
    print("Refreshed Withings tokens and updated secrets/withings_tokens.json")


if __name__ == "__main__":
    main()
