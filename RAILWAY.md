# Railway Deployment

This project can be deployed to Railway as a single always-on web service that
runs the Telegram bot and serves a Telegram Mini App backed by the latest
snapshot files already committed to the repository.

## Recommended setup

Use Railway for the combined web app + polling bot service:

- deploy the app as one persistent web service
- set `TG_BOT_TOKEN` in Railway variables
- set `APP_BASE_URL` to the Railway public URL
- keep refreshing snapshots locally
- commit updated CSV/PDF files to GitHub
- let Railway redeploy from the updated repository

This is the simplest setup because the bot only needs local files that are
already in the repo.

## Why this setup

Right now, the most reliable workflow for this project is manual refresh:

- Transfermarkt may challenge automated refreshes with human verification
- the bot itself only needs the latest local files under `tmstats/`
- Railway is good for the always-on Telegram process plus Mini App hosting

## Deploy steps

1. Push the latest code and snapshots to GitHub.
2. In Railway, create a new project.
3. Choose `Deploy from GitHub repo`.
4. Select this repository.
5. Let Railway create a single service.
6. In the service variables, add:

```env
TG_BOT_TOKEN=your-real-telegram-token
APP_BASE_URL=https://your-service.up.railway.app
```

7. In service variables, add this too if Railway has already built the service
   with Python `3.13`:

```env
NIXPACKS_PYTHON_VERSION=3.11
```

8. In service settings, set the Start Command to:

```bash
python main.py
```

9. Make sure the Railway service has a public generated domain enabled.

10. Deploy the service.

11. After the deploy succeeds, open the logs once and confirm you see the bot
    username printed at startup.

12. Open Telegram and send `/start`. The bot should offer an `Open Mini App`
    button, and the chat menu button should also open the app.

## Notes

- `main.py` starts both the Telegram polling bot and the Mini App web server.
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
- or explicitly set the service Start Command to `python main.py`

If the service starts but the bot does not answer in Telegram:

- confirm `TG_BOT_TOKEN` is set correctly in Railway
- confirm `APP_BASE_URL` matches the public Railway domain
- check Railway deployment logs for startup errors
- redeploy after updating variables

If the bot works but the Mini App button does not appear:

- confirm the Railway service has a public domain
- confirm `APP_BASE_URL` is set to that exact HTTPS URL
- redeploy after updating the variable
