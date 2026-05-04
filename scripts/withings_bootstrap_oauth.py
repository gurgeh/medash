import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from withings_api import WithingsAuth

from src.withings_client import WithingsClient


def build_auth() -> WithingsAuth:
    client_id = os.environ["WITHINGS_CLIENT_ID"]
    client_secret = os.environ["WITHINGS_CLIENT_SECRET"]
    callback = os.environ.get("WITHINGS_CALLBACK_URL", "http://localhost:9876/callback")
    scope = WithingsClient.scopes()
    return WithingsAuth(
        client_id=client_id,
        consumer_secret=client_secret,
        callback_uri=callback,
        scope=scope,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if "/callback" in self.path and "code" in qs:
            code = qs["code"][0]
            auth = build_auth()
            creds = auth.get_credentials(code)
            WithingsClient.save_tokens(creds)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Withings OAuth complete. You can close this window.")
            raise SystemExit(0)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    load_dotenv()
    auth = build_auth()
    url = auth.get_authorize_url()
    print("Open this URL and authorize:")
    print(url)
    print()
    host = "127.0.0.1"
    port = int(os.environ.get("WITHINGS_CALLBACK_PORT", "9876"))
    httpd = HTTPServer((host, port), Handler)
    print(f"Waiting for callback on http://{host}:{port}/callback ...")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
