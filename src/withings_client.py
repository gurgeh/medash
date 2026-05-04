import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from withings_api import WithingsApi, Credentials2, AuthScope


TOKENS_PATH_DEFAULT = Path("secrets/withings_tokens.json")


@dataclass
class StoredCredentials:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    userid: int
    client_id: str
    consumer_secret: str

    @classmethod
    def from_credentials(cls, c: Credentials2) -> "StoredCredentials":
        return cls(
            access_token=c.access_token,
            refresh_token=c.refresh_token,
            token_type=c.token_type,
            expires_in=int(c.expires_in),
            userid=int(c.userid),
            client_id=str(c.client_id),
            consumer_secret=str(c.consumer_secret),
        )

    def to_credentials(self) -> Credentials2:
        return Credentials2(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            expires_in=self.expires_in,
            userid=self.userid,
            client_id=self.client_id or os.environ.get("WITHINGS_CLIENT_ID", ""),
            consumer_secret=self.consumer_secret or os.environ.get("WITHINGS_CLIENT_SECRET", ""),
        )


class WithingsClient:
    def __init__(self, credentials: Credentials2):
        self.credentials = credentials
        # Persist refreshed tokens automatically
        self.api = WithingsApi(credentials, refresh_cb=lambda c: WithingsClient.save_tokens(c))

    @classmethod
    def from_tokens_file(cls, path: Path | str = TOKENS_PATH_DEFAULT) -> "WithingsClient":
        path = Path(path)
        data = json.loads(path.read_text())
        stored = StoredCredentials(**data)
        return cls(stored.to_credentials())

    @staticmethod
    def save_tokens(creds: Credentials2, path: Path | str = TOKENS_PATH_DEFAULT) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = StoredCredentials.from_credentials(creds)
        path.write_text(json.dumps(asdict(stored), indent=2))

    @classmethod
    def scopes(cls):
        return (AuthScope.USER_INFO, AuthScope.USER_METRICS)

    def get_measures_last30(self) -> Any:
        end = date.today()
        start = end - timedelta(days=30)
        # Important: pass lastupdate=None to avoid default filtering to "now".
        return self.api.measure_get_meas(startdate=start, enddate=end, lastupdate=None)
