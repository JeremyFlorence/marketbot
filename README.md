# marketbot

A Discord bot that reports stock and crypto prices and plots price history as
charts, using [Massive](https://massive.com) (formerly Polygon.io) for market data.

## Commands

All commands use the `$` prefix.

| Command | Description | Example |
| --- | --- | --- |
| `$price SYMBOL [SYMBOL ...]` | Latest price and daily change for one or more stocks. | `$price AAPL MSFT TSLA` |
| `$plot_today SYMBOL` | Chart of the most recent session at a 5-minute interval. | `$plot_today AAPL` |
| `$plot_range SYMBOL START END` | Chart of a date range. Dates are `MM-DD-YYYY`. The sampling interval is chosen from the range length (weekly ≥ 2 years, daily ≥ 1 month, hourly ≥ 5 days, otherwise 30-minute). | `$plot_range AAPL 01-01-2025 06-01-2025` |
| `$crypto_current_price SYMBOL MARKET` | Latest price for a crypto pair. | `$crypto_current_price BTC USD` |

## Setup

### 1. Discord application

1. Create an application at <https://discord.com/developers/applications>.
2. **Bot** tab → add a bot → copy the **token** (this is `DISCORD_TOKEN`).
3. **Bot** tab → **Privileged Gateway Intents** → enable **Message Content
   Intent**. The bot uses prefix commands, so it cannot read command text
   without this and will fail to start with `PrivilegedIntentsRequired`.
4. **OAuth2 → URL Generator** → scope **`bot`**, permissions **View Channels**,
   **Send Messages**, **Attach Files**, **Read Message History**. Open the
   generated URL to invite the bot to a server. The `bot` scope is required —
   inviting with only `applications.commands` adds the app but no bot user.

### 2. Massive API key

Create a key at <https://massive.com/dashboard/keys>. This is `MASSIVE_API_KEY`.

### 3. Environment variables

The bot reads two variables:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token |
| `MASSIVE_API_KEY` | Massive API key |

## Running locally

Requires **Python 3.9+** (`massive` and current `matplotlib` drop older versions).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DISCORD_TOKEN=...
export MASSIVE_API_KEY=...
python3 marketbot.py
```

On success the bot prints `Logged in as` and its user name. It appears offline
in the member list until this process is running.

## Deploying (Heroku)

The repo includes a `Procfile` (`worker: python3 marketbot.py`) and a
`runtime.txt` pinning the Python version.

```bash
heroku create
heroku config:set DISCORD_TOKEN=... MASSIVE_API_KEY=...
git push heroku master
heroku ps:scale worker=1
```

## Data plan notes

The commands adapt to whatever the Massive API key is entitled to:

- **Paid plan** — `$price` and `$crypto_current_price` return real-time (or
  15-minute-delayed) snapshots, and `$plot_today` plots the current session.
- **Free plan** — snapshot and same-day endpoints are not available, so the bot
  falls back to the most recent **end-of-day** close. `$plot_today` then plots
  the previous session, and each response is stamped with the actual date.
  `$plot_range` history is limited to roughly the last 2 years; requests for
  older ranges plot only the portion that is available.

Upgrading the plan at <https://massive.com/pricing> enables the real-time paths
automatically — no code change needed.

## Repo layout

| File | Purpose |
| --- | --- |
| `marketbot.py` | The entire bot. |
| `requirements.txt` | Python dependencies. |
| `Procfile` / `runtime.txt` | Heroku process and Python version. |
