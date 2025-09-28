import os
from datetime import date

from dotenv import load_dotenv

from src.garmin_client import GarminClient


def main():
    load_dotenv()

    client = GarminClient.from_env()
    client.login()
    data = client.steps_today()
    print(f"Steps for {date.today().isoformat()}:")
    print(data)
    # No explicit logout; tokens persist under secrets/garmin_tokens


if __name__ == "__main__":
    main()
