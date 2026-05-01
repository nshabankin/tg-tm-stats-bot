
# tg-tm-stats-bot

A Telegram [bot](https://t.me/GetFootballStatsBot) that lets users browse
football snapshots from local data files.

It currently supports:

- league table snapshots
- domestic matchday snapshots
- UEFA league-phase snapshots
- UEFA knockout bracket snapshots
- player stats snapshots
- Telegram Mini App browsing
- in-chat fallback browsing in Telegram
- optional CSV and PDF snapshot generation in the local refresh pipeline

![tg-tm-stats-bot-logo](https://i.ibb.co/28zqyxC/photo-2022-06-15-13-54-05.jpg)

## What The Bot Does

The bot shows a list of supported leagues. After a user picks a league, it can:

- show the current league table directly in Telegram
- let the user browse teams ordered by table position
- let the user browse players inside a team, sorted by shirt number
- show an individual player's stats directly in Telegram

The bot does not generate data on demand. It reads the newest local snapshot
already present in `tmstats/<league>/`.

The current UX is browse-first:

- open the Mini App from Telegram
- pick a league
- browse the table as dense standings rows
- open teams as collapsible squad bubbles
- browse domestic and UEFA match results in the `Matches` tab
- open knockout brackets for UEFA competitions in the `Playoffs` tab
- open individual player stat cards
- use league logos in the picker instead of flag-only chips
- see match rows normalized to the snapshot club names, so full names and logos stay aligned

There is also a simpler in-chat fallback path for cases where the Mini App is
not configured yet.

## Current Status

This project started as an older Telegram bot plus scraper setup and has been
revived into a local-first workflow:

- the bot can run locally as a combined web service and Telegram bot
- snapshots are refreshed manually with `refresh_data.py`
- the bot reads the latest available local CSV snapshots
- the bot reads local JSON match snapshots alongside table and player snapshots
- CSV and PDF exports can be generated alongside those snapshots
- team logos can be refreshed into the table snapshots for Mini App display
- league tables now include recent five-match form when Transfermarkt exposes it
- the Telegram UX is optimized for the Mini App first, not bulk file downloads
- legacy Scrapy and queue-worker code has been removed from the active project

This means the most reliable operating model right now is:

1. refresh league data manually when you want fresh snapshots
2. regenerate PDFs if you want archival/downloadable files
3. run the service so it serves the newest local snapshot data in Telegram

## Supported Leagues

- `epl`
- `la_liga`
- `serie_a`
- `bundesliga`
- `ligue_1`
- `rpl`
- `ucl`
- `uel`
- `uecl`

New competitions only show up in Telegram once their local snapshots exist.
That keeps the picker honest and avoids exposing empty competitions before their
first refresh.

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
APP_BASE_URL=
TM_COOKIE=
PDF_FONT_PATH=
```

Start the combined local service:

```bash
python main.py
```

## Environment Variables

`TG_BOT_TOKEN`

- Required
- Telegram bot token used by `bot.py`

`TM_COOKIE`

- Optional, but often needed for live refreshes
- Browser cookie string copied from an authenticated / human-verified
  Transfermarkt session
- If player-page refreshes start printing many human-verification warnings,
  refresh this cookie before trusting or committing the regenerated snapshots

`PDF_FONT_PATH`

- Optional
- Path to a specific font file to use for PDF rendering if the default font
  detection still misses some characters

`APP_BASE_URL`

- Optional locally, but required for Telegram Mini App launch buttons
- Public HTTPS base URL where the Mini App is served
- Example: `https://your-app.up.railway.app`

## How Snapshot Naming Works

Snapshot filenames use the season start year, not the calendar year.

Example:

- `epl_stats_2025.csv` means the `2025/26` season

So on April 7, 2026, the current season is still labeled `2025`.

## Refresh Data

The refresh script pulls the current Transfermarkt season dynamically.

This project is intentionally run as a gentle, manual scraper:

- refreshes are triggered manually, not in a tight unattended loop
- requests are throttled with a configurable delay
- regular refreshes reuse the saved season roster by default, because
  mid-season player lists rarely change compared with the player stat pages
- if Transfermarkt asks for human verification, the expected response is to
  stop, refresh your own browser session, and try again later
- if a refresh starts printing many player-level warnings, do not commit those
  regenerated CSV/PDF files until you verify the affected league snapshots
- the project is meant to create occasional personal snapshot files, not to
  mirror or hammer the source site

Refresh one league:

```bash
python refresh_data.py --league epl
```

Refresh one UEFA competition:

```bash
python refresh_data.py --league ucl
```

Refresh all leagues with a full stats rebuild:

```bash
python refresh_data.py --all
```

Use this when you intentionally want to rebuild every saved player-stat
snapshot. For routine catch-up work, prefer the targeted command below.

Force a fresh roster pull when you actually need to rebuild squads, for example
around transfer windows:

```bash
python refresh_data.py --all --refresh-rosters
```

Force a specific season:

```bash
python refresh_data.py --league epl --season 2025
```

Refresh only team logo URLs inside existing table snapshots:

```bash
python refresh_data.py --all --logos-only
```

Use `--logos-only` as a light visual refresh for existing table snapshots. If
standings and squads have moved materially since the last run, prefer a full
refresh so clubs, logos, table positions, and players all stay aligned.

For midweek catch-up runs where only a few matches finished, use targeted team
refreshes:

```bash
python refresh_data.py --all --changed-team-stats
```

That mode:

- refreshes the live table and match snapshots for each selected league
- compares the new match JSON against the saved one
- detects clubs from fixtures whose score changed from empty to played, or whose
  score changed since the last snapshot
- refreshes only those clubs' rosters and player stats
- writes a per-league refresh state snapshot so you can inspect what changed
  without diffing CSV/JSON files manually

This is the recommended regular refresh command. It avoids unnecessary player
stat refreshes when a league has no newly completed matches, and in late-stage
UEFA weeks it refreshes only the clubs involved in changed knockout fixtures
instead of rebuilding every league-phase squad.

If the baseline CSV/JSON snapshots are missing, it falls back to a full league
refresh for safety.

The refresh writes files into `tmstats/<league>/`.
When a CSV or JSON snapshot does not actually change, the refresh now skips the
rewrite and avoids regenerating the matching PDF unnecessarily.

The stats refresh reads Transfermarkt's structured player-performance data
first, then falls back to the older player-page parser if needed. If a
per-player API request has a transient failure and the old page no longer
contains a usable stats table, the script preserves that player's existing
stats row instead of writing blanks. Treat repeated human-verification or
player-level warnings as a failed refresh signal rather than as valid zero-stat
data.

For example, an EPL refresh produces files like:

- `tmstats/epl/epl_players_2025.csv`
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

## Verification

Run the local smoke checks for the refresh pipeline with:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

These tests stay off the network and cover the refactored refresh entrypoint,
shared context setup, pipeline helpers, and targeted changed-team control flow.

## Bot Usage

Run the combined service:

```bash
source .venv/bin/activate
python main.py
```

Then in Telegram:

1. send `/start`
2. tap `Open Mini App` for the full experience
3. choose a league inside the Mini App
4. switch between `Table`, `Teams`, and `Matches`
5. in `Teams`, expand a club bubble to see its squad
6. for UEFA competitions, open `Playoffs` to browse the knockout rounds
7. tap a player to open their stat card

If `APP_BASE_URL` is not configured yet, the bot falls back to the simpler
inline chat flow.

## Project Layout

`bot.py`

- Telegram bot entrypoint
- Opens the Mini App when available
- Keeps the in-chat fallback browse flow

`main.py`

- Combined launcher for the web service and Telegram polling bot

`webapp.py`

- Flask application serving the Mini App and JSON snapshot endpoints

`refresh_data.py`

- CLI entrypoint for data refresh and PDF-only regeneration

`tmstats/refresh.py`

- Main refresh pipeline
- Pulls current standings, recent team form, and player data
- Writes player and table snapshot CSV files
- Can refresh only clubs involved in newly completed matches with
  `--changed-team-stats`
- Writes `*_refresh_state_<season>.json` summaries alongside league snapshots
- Can refresh only team logo URLs with `--logos-only`
- Optionally renders PDF exports from those snapshots

`tmstats/catalog.py`

- Shared league metadata used by both the bot and the refresh pipeline

`tmstats/snapshots.py`

- Shared snapshot discovery logic used by the bot

`tmstats/browse.py`

- Local snapshot loading, team/player lookup, and Telegram text formatting

`tmstats/miniapp.py`

- Snapshot serialization for the Mini App JSON API

`tmstats/pdf_export.py`

- PDF renderer for table and player snapshots

`tmstats/<league>/`

- Snapshot storage for each league

## Railway Hosting

This bot is a good candidate for a single Railway web service if you want it
running continuously without keeping your local machine on.

Recommended Railway model:

- host the web service and the polling bot together on Railway
- keep manual refreshes local
- commit refreshed CSV/PDF snapshots to GitHub
- let Railway autodeploy the new commit

Quick summary:

1. push the repo to GitHub
2. create a Railway project from the GitHub repo
3. set `TG_BOT_TOKEN` in Railway variables
4. set `APP_BASE_URL` to your public Railway URL
5. set the Railway start command to `python main.py`

This setup uses Telegram long polling for the bot and also serves the Mini App
over HTTPS from the same Railway service.

Recommended workflow:

1. refresh data locally on your machine
2. commit updated snapshots to GitHub
3. let Railway redeploy automatically
4. use Railway as the always-on bot host and Mini App server

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

If the refresh prints many player-level warnings and still completes:

1. do not commit the regenerated snapshot files yet
2. spot-check a few affected players in `tmstats/<league>/<league>_stats_<season>.csv`
3. refresh your browser cookie again
4. rerun the league refresh
5. only commit the snapshot once the blank stat rows are gone or understood

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
- The scraper is intentionally conservative and should stay that way.
- League tables are now pulled from the current standings page, not from
  Matchday 1.
- The primary user experience is now the Telegram Mini App, with in-chat
  browsing kept as a fallback.
