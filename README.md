
# tg-tm-stats-bot

A Telegram [bot](https://t.me/GetFootballStatsBot) that delivers football
snapshots as downloadable files.

It currently supports:

- league table snapshots
- player stats snapshots
- CSV and PDF downloads from Telegram

![tg-tm-stats-bot-logo](https://i.ibb.co/28zqyxC/photo-2022-06-15-13-54-05.jpg)

## What The Bot Does

The bot shows a list of supported leagues. After a user picks a league, it
offers four download options:

- `League Table (CSV)`
- `League Table (PDF)`
- `Player Stats (CSV)`
- `Player Stats (PDF)`

The bot does not generate data on demand. It serves the newest local snapshot
already present in `tmstats/<league>/`.

## Current Status

This project started as an older Telegram bot plus scraper setup and has been
revived into a local-first workflow:

- the bot runs locally with `python bot.py`
- snapshots are refreshed manually with `refresh_data.py`
- the bot serves the latest available local files
- CSV and PDF exports are generated side by side
- league tables now include recent five-match form when Transfermarkt exposes it
- legacy Scrapy and queue-worker code has been removed from the active project

This means the most reliable operating model right now is:

1. refresh league data manually when you want fresh snapshots
2. regenerate PDFs if needed
3. run the bot so it serves the newest local files

## Supported Leagues

- `epl`
- `la_liga`
- `serie_a`
- `bundesliga`
- `ligue_1`
- `rpl`

## Quick Start

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` and set:

```env
TG_BOT_TOKEN=your-telegram-bot-token
TM_COOKIE=
PDF_FONT_PATH=
```

Start the bot:

```bash
python bot.py
```

## Environment Variables

`TG_BOT_TOKEN`

- Required
- Telegram bot token used by `bot.py`

`TM_COOKIE`

- Optional, but often needed for live refreshes
- Browser cookie string copied from an authenticated / human-verified
  Transfermarkt session

`PDF_FONT_PATH`

- Optional
- Path to a specific font file to use for PDF rendering if the default font
  detection still misses some characters

## How Snapshot Naming Works

Snapshot filenames use the season start year, not the calendar year.

Example:

- `epl_stats_2025.csv` means the `2025/26` season

So on April 7, 2026, the current season is still labeled `2025`.

## Refresh Data

The refresh script pulls the current Transfermarkt season dynamically.

Refresh one league:

```bash
python refresh_data.py --league epl
```

Refresh all leagues:

```bash
python refresh_data.py --all
```

Force a specific season:

```bash
python refresh_data.py --league epl --season 2025
```

The refresh writes files into `tmstats/<league>/`.

For example, an EPL refresh produces files like:

- `tmstats/epl/epl_table_2025.csv`
- `tmstats/epl/epl_table_2025.pdf`
- `tmstats/epl/epl_stats_2025.csv`
- `tmstats/epl/epl_stats_2025.pdf`

## Generate PDFs Only

If CSV snapshots already exist and you only want to create or recreate PDFs,
use `--pdf-only`.

Example:

```bash
python refresh_data.py --league epl --season 2025 --pdf-only
```

This does not contact Transfermarkt. It reads the local CSV files and renders
the PDFs again.

## Bot Usage

Run the bot:

```bash
source .venv/bin/activate
python bot.py
```

Then in Telegram:

1. send `/start`
2. choose a league
3. choose dataset and format
4. receive the newest local snapshot file

## Project Layout

`bot.py`

- Telegram bot entrypoint
- Reads the latest local snapshot and sends it to the user

`refresh_data.py`

- CLI entrypoint for data refresh and PDF-only regeneration

`tmstats/refresh.py`

- Main refresh pipeline
- Pulls current standings, recent team form, and player data
- Writes league table and player snapshot CSV/PDF files

`tmstats/catalog.py`

- Shared league metadata used by both the bot and the refresh pipeline

`tmstats/snapshots.py`

- Shared snapshot discovery logic used by the bot

`tmstats/pdf_export.py`

- PDF renderer for table and player snapshots

`tmstats/<league>/`

- Snapshot storage for each league

## Railway Hosting

This bot is a good candidate for a single Railway service if you want it
running continuously without keeping your local machine on.

Recommended Railway model:

- host only the bot process on Railway
- keep manual refreshes local
- commit refreshed CSV/PDF snapshots to GitHub
- let Railway autodeploy the new commit

Quick summary:

1. push the repo to GitHub
2. create a Railway project from the GitHub repo
3. set `TG_BOT_TOKEN` in Railway variables
4. set the Railway start command to `python bot.py`

This bot uses Telegram long polling, so Railway does not need to expose a
public port for it.

Railway should run this project on Python `3.11`. The repo includes a
`.python-version` file for that because the pinned Telegram bot library is not
compatible with Python `3.13`.

For the full step-by-step guide, see [RAILWAY.md](/Users/nikitashabankin/Documents/tg_tm_stats_bot/RAILWAY.md).

## Troubleshooting

### Transfermarkt human verification

If refresh fails with a human-verification or CAPTCHA-style error:

1. open Transfermarkt in your browser
2. solve the challenge there
3. open browser developer tools
4. copy the full `Cookie` request header value
5. put it into `TM_COOKIE` in `.env`
6. rerun the refresh command

### PDF character issues

If a PDF still shows a missing character:

1. set `PDF_FONT_PATH` in `.env` to a font file on your machine
2. rerun:

```bash
python refresh_data.py --league epl --season 2025 --pdf-only
```

The CSV data remains untouched. Only the PDF rendering changes.

### `urllib3` LibreSSL warning on macOS

You may see a warning like this on macOS:

`urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'`

This warning is noisy but it is not the main cause of the Transfermarkt
verification issue.

## Notes

- The bot currently works best as a manually refreshed snapshot bot.
- Player stats are considered current as of the moment you run refresh.
- The live app no longer depends on Scrapy, Redis, RQ, or the old spider stack.
- League tables are now pulled from the current standings page, not from
  Matchday 1.
