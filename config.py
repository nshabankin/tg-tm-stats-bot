import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


def get_bot_token() -> str:
    """Return the Telegram bot token from the environment."""
    token = os.getenv('TG_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')

    if token:
        return token.strip()

    raise RuntimeError(
        'Telegram bot token is missing. Set TG_BOT_TOKEN in your shell '
        'or in a local .env file.'
    )
