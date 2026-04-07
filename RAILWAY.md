# Railway Deployment

This project can be deployed to Railway as a single always-on service that
runs the Telegram bot and serves the latest snapshot files already committed to
the repository.

## Recommended setup

Use Railway only for the bot process:

- deploy the bot as one persistent service
- set `TG_BOT_TOKEN` in Railway variables
- keep refreshing snapshots locally
- commit updated CSV/PDF files to GitHub
- let Railway redeploy from the updated repository

This is the simplest setup because the bot only needs local files that are
already in the repo.

This bot uses Telegram long polling, so it does not need an exposed HTTP port
or a public domain. Railway only needs to keep the Python process running.

## Why this setup

Right now, the most reliable workflow for this project is manual refresh:

- Transfermarkt may challenge automated refreshes with human verification
- the bot itself only needs the latest local files under `tmstats/`
- Railway is good for the always-on Telegram process

## Deploy steps

1. Push the latest code and snapshots to GitHub.
2. In Railway, create a new project.
3. Choose `Deploy from GitHub repo`.
4. Select this repository.
5. Let Railway create a single service.
6. In the service variables, add:

```env
TG_BOT_TOKEN=your-real-telegram-token
```

7. In service variables, add this too if Railway has already built the service
   with Python `3.13`:

```env
NIXPACKS_PYTHON_VERSION=3.11
```

8. In service settings, set the Start Command to:

```bash
python bot.py
```

9. Deploy the service.

10. After the deploy succeeds, open the logs once and confirm you see the bot
   username printed at startup.

## Notes

- A `main.py` file exists in the repo so Railway's Python detection has a
  standard entrypoint available, but setting the start command explicitly to
  `python bot.py` is still recommended.
- You do not need `TM_COOKIE` on Railway unless you also plan to refresh data
  there.
- You do not need a Railway volume for the initial setup if snapshots are
  committed to GitHub.
- Railway can run this as an always-on service, but because the bot keeps a
  persistent polling process alive, treat it as a small paid/usage-based
  service rather than assuming it will stay free forever.
- The repo includes a `.python-version` file pinned to `3.11` because
  `python-telegram-bot==12.7` is too old for Python `3.13`.

## Updating snapshots

When you refresh snapshots locally:

1. Run the refresh locally.
2. Commit the updated `tmstats/<league>/` CSV/PDF files.
3. Push to GitHub.
4. Railway autodeploys the new commit.

## Troubleshooting

If Railway says it cannot find a Python start command:

- confirm the repo contains `main.py`
- or explicitly set the service Start Command to `python bot.py`

If the service starts but the bot does not answer in Telegram:

- confirm `TG_BOT_TOKEN` is set correctly in Railway
- check Railway deployment logs for startup errors
- redeploy after updating variables
