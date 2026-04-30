import datetime
import sqlite3
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from analytics import get_dashboard_data

app = FastAPI()
# Change this to a random, secure string for your VPS
app.add_middleware(SessionMiddleware, secret_key="super-secret-bike-key-2026")
templates = Jinja2Templates(directory=".")

# --- Config ---
USER_PASSWORD = "yourpassword"  # The password to unlock the app on your phone
LAT, LON = 55.71, 12.50  # Example: Herlev, Denmark
CONTACT_EMAIL = "your@email.com"
TIMEZONE = ZoneInfo("Europe/Copenhagen")


# --- Database Setup ---
def get_db():
    # Add check_same_thread=False here
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


init_db()


# --- Auth Dependency ---
async def check_auth(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(
            status_code=307, detail="Auth required", headers={"Location": "/login"}
        )
    return True


# --- API Fetcher (MET Norway) ---
async def get_departure_data():
    headers = {"User-Agent": f"BikePredictorApp/1.0 ({CONTACT_EMAIL})"}
    today = datetime.datetime.now(TIMEZONE).date().isoformat()

    nowcast_url = (
        f"https://api.met.no/weatherapi/nowcast/2.0/complete?lat={LAT}&lon={LON}"
    )
    sun_url = f"https://api.met.no/weatherapi/sunrise/3.0/sun?lat={LAT}&lon={LON}&date={today}"

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
            # 1. Fetch Nowcast
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

            # 2. Fetch Sunrise/Sunset
            s_res = await client.get(sun_url, headers=headers)
            if s_res.status_code == 200:
                s_props = s_res.json()["properties"]
                data["sunrise"] = s_props["sunrise"]["time"].split("T")[1][:5]
                data["sunset"] = s_props["sunset"]["time"].split("T")[1][:5]

        except Exception as e:
            print(f"Error fetching MET data: {e}")

    return data


# --- Routes ---


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "login_mode": True},
    )


@app.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if password == USER_PASSWORD:
        request.session["logged_in"] = True
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    # We ONLY look for an active ride to show the start form or the timer
    active = db.execute("SELECT * FROM rides WHERE end_time IS NULL LIMIT 1").fetchone()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "active_ride": active, "login_mode": False},
    )


@app.get("/history", response_class=HTMLResponse)
async def get_history(
    request: Request, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    # Get completed rides
    cursor = db.execute(
        "SELECT * FROM rides WHERE end_time IS NOT NULL ORDER BY id DESC LIMIT 15"
    )
    history_rows = cursor.fetchall()

    history = []
    fmt = "%Y-%m-%d %H:%M:%S"

    for row in history_rows:
        # Convert sqlite3.Row to a standard dictionary
        ride = dict(row)

        start_str = ride.get("start_time")
        end_str = ride.get("end_time")

        if start_str and end_str:
            try:
                t1 = datetime.datetime.fromisoformat(start_str)
                t2 = datetime.datetime.fromisoformat(end_str)

                duration = t2 - t1
                total_secs = int(duration.total_seconds())

                hours, rem = divmod(total_secs, 3600)
                mins, secs = divmod(rem, 60)
                ride["duration"] = f"{hours:02}:{mins:02}:{secs:02}"
                ride["start_str"] = t1.astimezone(TIMEZONE).strftime(fmt)
                ride["end_str"] = t2.astimezone(TIMEZONE).strftime(fmt)
            except ValueError:
                ride["duration"] = "Error"
        else:
            ride["duration"] = "Incomplete"

        history.append(ride)

    return templates.TemplateResponse(
        request=request,
        name="history_snippet.html",
        context={"rides": history},
    )


@app.post("/start")
async def start_ride(
    route: str = Form(...),
    direction: str = Form(...),
    extra_dist: bool = Form(False),
    db: sqlite3.Connection = Depends(get_db),
    auth=Depends(check_auth),
):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    w = await get_departure_data()

    db.execute(
        """
        INSERT INTO rides (
            route, direction, extra_dist, start_time, 
            temp, precip_instant, precip_next_hour, humidity, 
            wind_dir, wind_speed, wind_gust, symbol, sunrise, sunset
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
        (
            route,
            direction,
            1 if extra_dist else 0,
            now,
            w["temp"],
            w["precip_instant"],
            w["precip_next_hour"],
            w["hum"],
            w["w_dir"],
            w["w_spd"],
            w["w_gst"],
            w["symbol"],
            w["sunrise"],
            w["sunset"],
        ),
    )
    db.commit()

    return RedirectResponse(url="/", status_code=303)


@app.post("/stop/{ride_id}")
async def stop_ride(
    ride_id: int, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    end_time = datetime.datetime.now(datetime.UTC).isoformat()
    db.execute("UPDATE rides SET end_time = ? WHERE id = ?", (end_time, ride_id))
    db.commit()
    return HTMLResponse("<script>window.location.reload()</script>")


@app.post("/cancel/{ride_id}")
async def cancel_ride(
    ride_id: int, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    db.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
    db.commit()
    return HTMLResponse("<script>window.location.reload()</script>")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, auth=Depends(check_auth)):
    # We pass the db path to our analytics module
    chart_json, stats = get_dashboard_data("bike_rides.db")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "chart_json": chart_json, "stats": stats},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
