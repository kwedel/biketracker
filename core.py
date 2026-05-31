import datetime
import sqlite3
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    USER_PASSWORD: str  # The password to unlock the app
    session_key: str  # For signing cookies
    LAT: float = 55.71  # Lattitude
    LON: float = 12.50  # Longitude
    CONTACT_EMAIL: str = "your@email.com"  # Email for the MET-API
    TIMEZONE: str = "Europe/Copenhagen"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
TIMEZONE = ZoneInfo(settings.TIMEZONE)

templates = Jinja2Templates(directory="templates")


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

    async with httpx.AsyncClient() as client:
        try:
            n_res = await client.get(nowcast_url, headers=headers)
            if n_res.status_code == 200:
                n_json = n_res.json()["properties"]["timeseries"][0]["data"]
                instant = n_json.get("instant", {}).get("details", {})
                next_hour = n_json.get("next_1_hours", {}).get("details", {})
                summary = n_json.get("next_1_hours", {}).get("summary", {})

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

            s_res = await client.get(sun_url, headers=headers)
            if s_res.status_code == 200:
                s_props = s_res.json()["properties"]
                data["sunrise"] = s_props["sunrise"]["time"]
                data["sunset"] = s_props["sunset"]["time"]

        except Exception as e:
            print(f"Error fetching MET data: {e}")

    return data


def get_wind_arrow(degrees):
    if degrees is None:
        return ""
    arrows = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    idx = int((degrees + 22.5) % 360 // 45)
    return arrows[idx]
