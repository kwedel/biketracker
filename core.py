import asyncio
import datetime
import logging
import sqlite3

import httpx
from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from config import TIMEZONE, cache, settings
from services.weather import fetch_nowcast, fetch_sun

logger = logging.getLogger("biketracker.core")

templates = Jinja2Templates(directory="templates")


# --- Database Setup ---
def get_db():
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with sqlite3.connect(settings.DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route TEXT, direction TEXT, extra_dist INTEGER,
                start_time TEXT, end_time TEXT,
                temp REAL, precip_instant REAL, precip_next_hour REAL,
                humidity REAL, wind_dir REAL, wind_speed REAL, wind_gust REAL,
                symbol TEXT, sunrise TEXT, sunset TEXT
            )
        """
        )


# --- Auth Dependency ---
async def check_auth(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(
            status_code=307, detail="Auth required", headers={"Location": "/login"}
        )
    return True


# --- API Fetcher (MET Norway) ---
async def get_departure_data():
    headers = {"User-Agent": f"BikePredictorApp/1.0 ({settings.CONTACT_EMAIL})"}
    today = datetime.datetime.now(TIMEZONE).date().isoformat()

    nowcast_url = f"https://api.met.no/weatherapi/nowcast/2.0/complete?lat={settings.LAT}&lon={settings.LON}"
    sun_url = f"https://api.met.no/weatherapi/sunrise/3.0/sun?lat={settings.LAT}&lon={settings.LON}&date={today}"

    data = {
        "temp": None,
        "precip_instant": None,
        "precip_next_hour": None,
        "hum": None,
        "w_dir": None,
        "w_spd": None,
        "w_gst": None,
        "symbol": "unknown",
        "sunrise": "N/A",
        "sunset": "N/A",
    }

    async with httpx.AsyncClient() as client:
        n_json, s_json = await asyncio.gather(
            fetch_nowcast(client, nowcast_url, headers),
            fetch_sun(client, sun_url, headers),
        )

        if n_json:
            try:
                n_data = n_json["properties"]["timeseries"][0]["data"]
                instant = n_data.get("instant", {}).get("details", {})
                next_hour = n_data.get("next_1_hours", {}).get("details", {})
                summary = n_data.get("next_1_hours", {}).get("summary", {})

                data.update(
                    {
                        "temp": instant.get("air_temperature"),
                        "precip_instant": instant.get("precipitation_rate"),
                        "precip_next_hour": next_hour.get("precipitation_amount"),
                        "hum": instant.get("relative_humidity"),
                        "w_dir": instant.get("wind_from_direction"),
                        "w_spd": instant.get("wind_speed"),
                        "w_gst": instant.get("wind_speed_of_gust"),
                        "symbol": summary.get("symbol_code", "unknown"),
                    }
                )
            except (KeyError, IndexError, ValueError):
                logger.exception("Error parsing nowcast data")

        if s_json:
            try:
                s_props = s_json["properties"]
                data["sunrise"] = s_props["sunrise"]["time"]
                data["sunset"] = s_props["sunset"]["time"]
            except (KeyError, ValueError):
                logger.exception("Error parsing sun data")

    return data
