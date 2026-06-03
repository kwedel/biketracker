import asyncio
import datetime
import email.utils
import logging
import sqlite3
from zoneinfo import ZoneInfo

import diskcache
import httpx
from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("biketracker.core")


class Settings(BaseSettings):
    USER_PASSWORD: str  # The password to unlock the app
    session_key: str  # For signing cookies
    LAT: float = 55.71  # Lattitude
    LON: float = 12.50  # Longitude
    CONTACT_EMAIL: str = "your@email.com"  # Email for the MET-API
    TIMEZONE: str = "Europe/Copenhagen"
    loglevel: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
TIMEZONE = ZoneInfo(settings.TIMEZONE)

templates = Jinja2Templates(directory="templates")

cache = diskcache.Cache(".cache")


# --- Database Setup ---
def get_db():
    conn = sqlite3.connect("bike_rides.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with sqlite3.connect("bike_rides.db") as conn:
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

    async def fetch_nowcast(client: httpx.AsyncClient):
        n_headers = headers.copy()
        cached = cache.get(nowcast_url)
        if cached:
            expires = cached.get("expires")
            if expires and datetime.datetime.now(datetime.UTC) < expires:
                logger.debug("Nowcast cache not expired - returning cached data")
                return cached["data"]

            last_mod = cached.get("last_modified")
            if last_mod:
                n_headers["If-Modified-Since"] = last_mod

        try:
            logger.debug("Fetching nowcast")
            res = await client.get(nowcast_url, headers=n_headers)
            if res.status_code == 304 and cached:
                logger.debug("Nowcast not modified - returning cached nowcast")
                return cached["data"]
            if res.status_code == 200:
                res_json = res.json()
                exp_str = res.headers.get("Expires")
                lm_str = res.headers.get("Last-Modified")
                exp_dt = None
                if exp_str:
                    try:
                        exp_dt = email.utils.parsedate_to_datetime(exp_str)
                    except Exception:
                        pass
                cache.set(
                    nowcast_url,
                    {"data": res_json, "expires": exp_dt, "last_modified": lm_str},
                )
                return res_json
        except Exception:
            logger.exception("Error fetching nowcast data")

        return cached["data"] if cached else None

    async def fetch_sun(client: httpx.AsyncClient):
        cached = cache.get(sun_url)
        if cached:
            return cached

        try:
            res = await client.get(sun_url, headers=headers)
            if res.status_code == 200:
                res_json = res.json()
                cache.set(sun_url, res_json, expire=86400)  # 24 hours
                return res_json
        except Exception:
            logger.exception("Error fetching sun data")
        return None

    async with httpx.AsyncClient() as client:
        n_json, s_json = await asyncio.gather(fetch_nowcast(client), fetch_sun(client))

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
            except (KeyError, IndexError, ValueError) as e:
                logger.exception("Error parsing nowcast data")

        if s_json:
            try:
                s_props = s_json["properties"]
                data["sunrise"] = s_props["sunrise"]["time"]
                data["sunset"] = s_props["sunset"]["time"]
            except (KeyError, ValueError) as e:
                logger.exception("Error parsing sun data")

    return data


def get_wind_arrow(degrees):
    if degrees is None:
        return ""
    arrows = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    idx = int((degrees + 22.5) % 360 // 45)
    return arrows[idx]
