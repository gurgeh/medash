import os
from datetime import date

# Requires: pip install garminconnect
from garminconnect import Garmin


def _build_prompt_mfa():
    totp_secret = os.environ.get("GARMIN_TOTP_SECRET")
    if totp_secret:
        import pyotp  # Requires: pip install pyotp
        totp = pyotp.TOTP(totp_secret)
        return lambda: totp.now()

    mfa_code = os.environ.get("GARMIN_MFA_CODE")
    if mfa_code:
        return lambda: mfa_code

    return None


class GarminClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._client = Garmin(
            self.username,
            self.password,
            prompt_mfa=_build_prompt_mfa(),
        )

    @classmethod
    def from_env(cls) -> "GarminClient":
        return cls(
            os.environ["GARMIN_USERNAME"],
            os.environ["GARMIN_PASSWORD"],
        )

    def login(self):
        # Token directory for persistence (override with GARMINTOKENS)
        token_dir = os.environ.get("GARMINTOKENS") or "secrets/garmin_tokens"

        oauth1_path = os.path.join(token_dir, "oauth1_token.json")
        oauth2_path = os.path.join(token_dir, "oauth2_token.json")

        if os.path.exists(oauth1_path) and os.path.exists(oauth2_path):
            # Load existing tokens instead of credential login
            self._client.login(tokenstore=token_dir)
        else:
            # Perform credential login, then persist tokens for next runs
            self._client.login()
            self._client.garth.dump(token_dir)

    def logout(self):
        self._client.logout()

    def steps_today(self):
        today = date.today().isoformat()
        return self._client.get_steps_data(today)
