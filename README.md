# 🌦 Cyberjaya Daily Weather Push Bot

Pushes a Bayesian multi-model rain probability forecast to Telegram every evening at **8 pm MYT**.

## What it does

- Fetches hourly rain probability from **7 NWP models** via two free APIs  
  (Open-Meteo: ECMWF, GFS, ICON, GEM, MeteoFrance, JMA · MET Norway)
- Runs a **Bayesian log-odds ensemble** with climatological prior
- Sends a formatted summary to your **Telegram** chat at 8 pm MYT via GitHub Actions (free)

## Sample message

```
🌦 Cyberjaya Daily Forecast
📅 Fri 13 Mar 2026
⏰ Window analysed: 3 pm – 5 pm MYT

⛈ Very Likely — 62% rain probability

Ensemble avg:    58%
Model spread:    ±9 pp  (HIGH confidence)
Prior (climate): 40%

Hourly breakdown (3–5 pm):
  15:00  ███████░░░  67%
  16:00  ████████░░  72%
  17:00  ██████░░░░  58%

7-model breakdown:
  ECMWF IFS        68%  (w=0.28)
  MET Norway       71%  (w=0.18)
  GFS 0.25°        55%  (w=0.16)
  ICON             60%  (w=0.14)
  GEM Global       52%  (w=0.08)
  MeteoFrance      50%  (w=0.08)
  JMA              49%  (w=0.08)

🌂 Bring an umbrella!

_Bayesian multi-model ensemble_
_Open-Meteo + MET Norway · 12:01 UTC_
```

## Setup (10 minutes)

### 1. Create a Telegram bot

1. Open Telegram → search **@BotFather** → `/newbot`
2. Follow the prompts → copy your **Bot Token** (looks like `123456789:ABCdef...`)
3. Message your new bot once (any text)
4. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
5. Find `"chat":{"id":XXXXXXX}` → copy that number as your **Chat ID**

### 2. Fork / upload this repo to GitHub

1. Create a free account at [github.com](https://github.com)
2. Click **+** → **New repository** → name it `cyberjaya-weather` → **Create**
3. Upload all files from this folder (drag & drop on the GitHub web UI)

### 3. Add secrets to GitHub

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:
   - `TELEGRAM_TOKEN` → your bot token from Step 1
   - `TELEGRAM_CHAT_ID` → your chat ID from Step 1

### 4. Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. Click **Enable Actions** if prompted
3. The workflow will now run automatically at **12:00 UTC (8pm MYT)** every day

### 5. Test it right now

1. Go to **Actions** → **Daily Weather Push** → **Run workflow** → **Run workflow**
2. Watch it run live — you should receive a Telegram message within ~30 seconds

## Cost

| Resource          | Cost   |
|-------------------|--------|
| GitHub Actions    | Free (2,000 min/month free; this uses ~30 min/month) |
| Open-Meteo API    | Free, no key required |
| MET Norway API    | Free, no key required |
| Telegram Bot API  | Free, no limits |
| **Total**         | **$0** |

## Files

```
cyberjaya-weather/
├── weather_push.py                    # Main script
├── requirements.txt                   # Python dependencies (just requests)
└── .github/
    └── workflows/
        └── daily_weather.yml          # GitHub Actions cron schedule
```
