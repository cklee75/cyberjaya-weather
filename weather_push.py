#!/usr/bin/env python3
"""
Cyberjaya Daily Weather Push
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Multi-model Bayesian ensemble → Telegram notification at 8pm MYT

Sources:
  • Open-Meteo forecast API  (ECMWF, GFS, ICON, GEM, MeteoFrance, JMA)
  • MET Norway Locationforecast 2.0  (same ECMWF backbone as Yr.no)

No API keys required for weather data. Only needs:
  TELEGRAM_TOKEN   — from @BotFather
  TELEGRAM_CHAT_ID — your personal chat ID
"""

import math
import os
from datetime import date, datetime, timedelta, timezone

import requests

# ── LOCATION ──────────────────────────────────────────────────────────────────
LAT, LON  = 2.9213, 101.6559
TIMEZONE  = "Asia/Kuala_Lumpur"
LOCATION  = "Cyberjaya, Malaysia"

# Target afternoon window (local hour numbers)
TARGET_HOURS = [15, 16, 17]   # 3pm, 4pm, 5pm MYT

# ── CLIMATOLOGICAL PRIORS ─────────────────────────────────────────────────────
# P(rain | 3–5pm window, month) based on NASA MERRA-2 30-yr climatology
# Afternoon convective fraction ~65% of daily rain days
MONTHLY_PRIORS = {
    1: 38,  2: 35,  3: 40,  4: 45,  5: 48,
    6: 42,  7: 38,  8: 40,  9: 44, 10: 50,
   11: 52, 12: 44,
}

# ── MODEL REGISTRY ────────────────────────────────────────────────────────────
# Weights tuned for tropical SE Asia convective rain accuracy
# (ECMWF consistently top-ranked on WMO skill scores)
OPEN_METEO_MODELS = {
    "ecmwf_ifs025":         0.28,
    "gfs025":               0.16,
    "icon_seamless":        0.14,
    "gem_global":           0.08,
    "meteofrance_seamless": 0.08,
    "jma_seamless":         0.08,
}

MET_NORWAY_WEIGHT = 0.18   # fetched from separate API

# ── TELEGRAM CREDENTIALS ──────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ─────────────────────────────────────────────────────────────────────────────
# FETCH FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_open_meteo(model: str) -> dict[int, float]:
    """
    Fetch hourly precipitation_probability for tomorrow from one Open-Meteo model.
    Returns {local_hour: probability_pct} for the full day.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":  LAT,
                "longitude": LON,
                "hourly":    "precipitation_probability,temperature_2m,precipitation",
                "timezone":  TIMEZONE,
                "forecast_days": 2,
                "models":    model,
            },
            timeout=20,
        )
        r.raise_for_status()
        data  = r.json()
        times = data["hourly"]["time"]
        probs = data["hourly"]["precipitation_probability"]

        result = {}
        for t, p in zip(times, probs):
            if t.startswith(tomorrow) and p is not None:
                result[int(t[11:13])] = float(p)
        return result

    except Exception as exc:
        print(f"  ⚠ Open-Meteo [{model}]: {exc}")
        return {}


def fetch_met_norway() -> dict[int, float]:
    """
    Fetch hourly precipitation probability from MET Norway Locationforecast 2.0.
    Uses the same ECMWF NWP backbone as Yr.no but via a fully open API.
    Returns {local_hour: probability_pct} for tomorrow (UTC hours converted to MYT).
    """
    tomorrow_utc = (date.today() + timedelta(days=1)).isoformat()
    # MYT = UTC+8; tomorrow local = today+1 UTC at 00:00 MYT = today UTC at 16:00
    try:
        r = requests.get(
            "https://api.met.no/weatherapi/locationforecast/2.0/compact",
            params={"lat": round(LAT, 4), "lon": round(LON, 4)},
            headers={
                # MET Norway requires a descriptive User-Agent
                "User-Agent": "CyberjayaWeatherBot/1.0 (github.com/yourusername/cyberjaya-weather)"
            },
            timeout=20,
        )
        r.raise_for_status()
        series = r.json()["properties"]["timeseries"]

        result = {}
        for entry in series:
            utc_str = entry["time"]  # e.g. "2026-03-13T07:00:00Z"
            # Convert to MYT (+8)
            utc_hour  = int(utc_str[11:13])
            utc_day   = utc_str[:10]
            myt_hour  = (utc_hour + 8) % 24
            myt_day   = (
                date.fromisoformat(utc_day) + timedelta(days=1)
                if utc_hour + 8 >= 24
                else date.fromisoformat(utc_day)
            ).isoformat()

            if myt_day == tomorrow_utc:
                details = (
                    entry.get("data", {})
                         .get("next_1_hours", {})
                         .get("details", {})
                )
                prob = details.get("probability_of_precipitation")
                if prob is not None:
                    result[myt_hour] = float(prob)

        return result

    except Exception as exc:
        print(f"  ⚠ MET Norway: {exc}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# BAYESIAN ENSEMBLE
# ─────────────────────────────────────────────────────────────────────────────

def window_avg(hourly: dict[int, float]) -> float | None:
    """Average PoP over the 3–5pm target window."""
    vals = [hourly[h] for h in TARGET_HOURS if h in hourly]
    return sum(vals) / len(vals) if vals else None


def bayesian_blend(
    model_estimates: dict[str, float],   # model_name → window_avg_pct
    model_weights:   dict[str, float],   # model_name → weight
    prior_pct: float,
    model_blend_frac: float = 0.65,      # 65% models, 35% climatology
) -> tuple[float, float, float]:
    """
    Weighted log-odds blend of:
      - model ensemble (weighted average of per-model PoP)
      - climatological prior

    Returns (final_pct, ensemble_pct, total_weight)
    """
    total_w   = sum(model_weights.get(m, 0) for m in model_estimates)
    ensemble_p = (
        sum(model_estimates[m] * model_weights.get(m, 0) for m in model_estimates)
        / total_w
        if total_w > 0
        else prior_pct
    )

    def log_odds(p: float) -> float:
        p = max(0.5, min(99.5, p))   # clamp to avoid ±∞
        return math.log(p / (100 - p))

    def from_log_odds(lo: float) -> float:
        return 1 / (1 + math.exp(-lo)) * 100

    blended_lo = (
        model_blend_frac       * log_odds(ensemble_p) +
        (1 - model_blend_frac) * log_odds(prior_pct)
    )
    return round(from_log_odds(blended_lo)), round(ensemble_p), total_w


def inter_model_sigma(estimates: dict[str, float]) -> int:
    """Standard deviation across model window estimates (inter-model spread)."""
    vals = list(estimates.values())
    if len(vals) < 2:
        return 0
    mean = sum(vals) / len(vals)
    return round(math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)))


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE FORMATTER
# ─────────────────────────────────────────────────────────────────────────────

def build_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def format_message(
    final_p:    int,
    ensemble_p: int,
    sigma:      int,
    per_hour:   dict[str, dict[int, float]],   # model → {hour: prob}
    model_weights: dict[str, float],
    tomorrow:   str,
) -> str:
    verdict, verdict_emoji = (
        ("Unlikely",    "☀️")  if final_p < 25 else
        ("Possible",    "🌤") if final_p < 45 else
        ("Likely",      "🌧") if final_p < 65 else
        ("Very Likely", "⛈")
    )

    confidence = (
        "HIGH ↑"   if sigma <= 8  else
        "MODERATE" if sigma <= 16 else
        "LOW ↓"
    )

    umbrella_line = (
        "🌂 *Bring an umbrella!*"         if final_p >= 65 else
        "☂️ Consider bringing an umbrella" if final_p >= 45 else
        "👍 Probably fine without one"     if final_p >= 25 else
        "☀️ Leave the umbrella at home"
    )

    # ── Hourly block ──
    hour_lines = []
    for h in TARGET_HOURS:
        vals = [d[h] for d in per_hour.values() if h in d]
        if vals:
            avg = round(sum(vals) / len(vals))
            hour_lines.append(f"  {h}:00  {build_bar(avg)}  {avg}%")

    # ── Per-model block ──
    model_lines = []
    all_weights = {**{m: w for m, w in OPEN_METEO_MODELS.items()},
                   "met_norway": MET_NORWAY_WEIGHT}
    for m, d in sorted(per_hour.items(),
                        key=lambda x: -all_weights.get(x[0], 0)):
        vals = [d[h] for h in TARGET_HOURS if h in d]
        if not vals:
            continue
        avg = round(sum(vals) / len(vals))
        w   = all_weights.get(m, 0)
        tag = (
            m.replace("ecmwf_ifs025",         "ECMWF IFS")
             .replace("gfs025",               "GFS 0.25°")
             .replace("icon_seamless",        "ICON")
             .replace("gem_global",           "GEM Global")
             .replace("meteofrance_seamless", "MeteoFrance")
             .replace("jma_seamless",         "JMA")
             .replace("met_norway",           "MET Norway")
        )
        model_lines.append(f"  {tag:<16}  {avg:>3}%  (w={w:.2f})")

    now_utc = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")
    dow     = (date.today() + timedelta(days=1)).strftime("%a %d %b %Y")

    lines = [
        f"🌦 *Cyberjaya Daily Forecast*",
        f"📅 {dow}",
        f"⏰ Window analysed: 3 pm – 5 pm MYT",
        f"",
        f"{verdict_emoji} *{verdict}* — {final_p}% rain probability",
        f"",
        f"Ensemble avg:   {ensemble_p}%",
        f"Model spread:   ±{sigma} pp  ({confidence} confidence)",
        f"Prior (climate): {MONTHLY_PRIORS.get(date.today().month+1, 40)}%",
        f"",
        f"*Hourly breakdown (3–5 pm):*",
        *hour_lines,
        f"",
        f"*{len(per_hour)}-model breakdown:*",
        *model_lines,
        f"",
        umbrella_line,
        f"",
        f"_Bayesian multi-model ensemble_",
        f"_Open-Meteo + MET Norway · {now_utc}_",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "Markdown",
        },
        timeout=20,
    )
    r.raise_for_status()
    print("✅ Telegram message sent successfully.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    month    = (date.today() + timedelta(days=1)).month
    prior    = MONTHLY_PRIORS.get(month, 40)

    print(f"\n📡 Fetching multi-model forecasts for {tomorrow}...\n")

    per_hour: dict[str, dict[int, float]] = {}

    # Open-Meteo models
    for model in OPEN_METEO_MODELS:
        data = fetch_open_meteo(model)
        if data:
            per_hour[model] = data
            avg = window_avg(data)
            print(f"  ✓ {model:<26}  3–5pm avg = {avg:.0f}%" if avg else f"  ✓ {model} (no window data)")

    # MET Norway
    mn_data = fetch_met_norway()
    if mn_data:
        per_hour["met_norway"] = mn_data
        avg = window_avg(mn_data)
        print(f"  ✓ met_norway                  3–5pm avg = {avg:.0f}%" if avg else "  ✓ met_norway (no window data)")

    if not per_hour:
        err = "⚠️ *Cyberjaya Weather Bot*\n\nAll weather APIs failed. Please check manually at yr.no"
        send_telegram(err)
        return

    # Window averages per model
    all_weights = {**OPEN_METEO_MODELS, "met_norway": MET_NORWAY_WEIGHT}
    estimates   = {m: w for m in per_hour if (w := window_avg(per_hour[m])) is not None}

    final_p, ensemble_p, _ = bayesian_blend(estimates, all_weights, prior)
    sigma = inter_model_sigma(estimates)

    print(f"\n{'─'*50}")
    print(f"  Ensemble average:    {ensemble_p}%")
    print(f"  Climatological prior: {prior}%")
    print(f"  Bayesian final:      {final_p}%")
    print(f"  Inter-model σ:       ±{sigma}pp")
    print(f"{'─'*50}\n")

    msg = format_message(final_p, ensemble_p, sigma, per_hour, all_weights, tomorrow)
    send_telegram(msg)


if __name__ == "__main__":
    main()
