#!/usr/bin/env python3
"""
Automated Angel One SmartAPI Session Generator.
Generates daily JWT and Feed tokens using TOTP 2FA before market open (8:45 AM IST)
and saves them to the .env file for continuous 24/7 cloud operation.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("angel_auto_login")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

def load_env_variables():
    """Loads variables from .env if available."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass

def update_env_file(env_file_path: Path, jwt_token: str, feed_token: str) -> bool:
    """Updates ANGEL_JWT_TOKEN and ANGEL_FEED_TOKEN in the specified .env file."""
    try:
        lines = []
        if env_file_path.exists():
            with open(env_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        jwt_found = False
        feed_found = False

        for line in lines:
            if line.strip().startswith("ANGEL_JWT_TOKEN="):
                new_lines.append(f"ANGEL_JWT_TOKEN={jwt_token}\n")
                jwt_found = True
            elif line.strip().startswith("ANGEL_FEED_TOKEN="):
                new_lines.append(f"ANGEL_FEED_TOKEN={feed_token}\n")
                feed_found = True
            else:
                new_lines.append(line)

        if not jwt_found:
            new_lines.append(f"ANGEL_JWT_TOKEN={jwt_token}\n")
        if not feed_found:
            new_lines.append(f"ANGEL_FEED_TOKEN={feed_token}\n")

        with open(env_file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        logger.info(f"Successfully updated Angel One tokens in {env_file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")
        return False

def generate_angel_session(
    api_key: str,
    client_code: str,
    pin: str,
    totp_key: str,
    mock_jwt: str = None,
    mock_feed: str = None
) -> tuple:
    """
    Generates Angel One JWT and Feed tokens using TOTP.
    If mock tokens are provided, returns them directly for dry-run/testing.
    """
    if mock_jwt and mock_feed:
        logger.info("Using mock Angel One session tokens.")
        return mock_jwt, mock_feed

    if not api_key or not client_code:
        raise ValueError("Missing ANGEL_API_KEY or ANGEL_CLIENT_CODE.")
    if not pin or not totp_key:
        raise ValueError("Missing ANGEL_PIN or ANGEL_TOTP_KEY for automated login.")

    try:
        import pyotp
        totp = pyotp.TOTP(totp_key).now()
        logger.info(f"Generated Angel One TOTP successfully: {totp[:2]}****")
    except Exception as e:
        raise RuntimeError(f"Failed to compute TOTP: {e}")

    try:
        from SmartApi import SmartConnect
        smart_api = SmartConnect(api_key=api_key)
        data = smart_api.generateSession(client_code, pin, totp)
        if data and data.get("status") and "data" in data:
            jwt = data["data"]["jwtToken"]
            feed = data["data"]["feedToken"]
            logger.info("Angel One session tokens generated successfully.")
            return jwt, feed
        else:
            msg = data.get("message", "Unknown error") if data else "No response"
            raise RuntimeError(f"Angel One session failed: {msg}")
    except Exception as e:
        logger.error(f"Error during SmartAPI session generation: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(description="Automated Angel One Session Generator")
    parser.add_argument("--dry-run", action="store_true", help="Simulate session without network calls")
    parser.add_argument("--mock-jwt", type=str, default=None, help="Mock JWT token")
    parser.add_argument("--mock-feed", type=str, default=None, help="Mock Feed token")
    parser.add_argument("--env-file", type=str, default=str(ENV_PATH), help="Target .env file path")
    args = parser.parse_args()

    load_env_variables()

    api_key = os.environ.get("ANGEL_API_KEY", "")
    client_code = os.environ.get("ANGEL_CLIENT_CODE", "")
    pin = os.environ.get("ANGEL_PIN", "")
    totp_key = os.environ.get("ANGEL_TOTP_KEY", "")

    target_env = Path(args.env_file)

    if args.dry_run:
        jwt = args.mock_jwt or "mock_angel_jwt_12345"
        feed = args.mock_feed or "mock_angel_feed_67890"
        update_env_file(target_env, jwt, feed)
        logger.info("Angel One dry-run session completed successfully.")
        return 0

    try:
        jwt, feed = generate_angel_session(api_key, client_code, pin, totp_key, mock_jwt=args.mock_jwt, mock_feed=args.mock_feed)
        update_env_file(target_env, jwt, feed)
        logger.info("Angel One token refresh completed.")
        return 0
    except Exception as e:
        logger.error(f"Angel One token refresh failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main() or 0)
