import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
TMSTATS_DIR = BASE_DIR / 'tmstats'
load_dotenv(BASE_DIR / '.env')


def get_env(name: str, default: str = '') -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def get_bot_token() -> str:
    """Return the Telegram bot token from the environment."""
    token = get_env('TG_BOT_TOKEN') or get_env('TELEGRAM_BOT_TOKEN')

    if token:
        return token

    raise RuntimeError(
        'Telegram bot token is missing. Set TG_BOT_TOKEN in your shell '
        'or in a local .env file.'
    )
