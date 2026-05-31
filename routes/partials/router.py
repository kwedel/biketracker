import datetime
import random
import sqlite3

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from core import (
    TIMEZONE,
    check_auth,
    get_db,
    get_departure_data,
    get_wind_arrow,
    templates,
)

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
async def get_history(
    request: Request, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    cursor = db.execute(
        "SELECT * FROM rides WHERE end_time IS NOT NULL ORDER BY id DESC LIMIT 15"
    )
    history_rows = cursor.fetchall()

    history = []
    fmt = "%d/%m %H:%M"

    for row in history_rows:
        ride = dict(row)
        start_time_raw = ride.get("start_time")
        end_time_raw = ride.get("end_time")

        if start_time_raw and end_time_raw:
            try:
                t1_utc = datetime.datetime.fromisoformat(start_time_raw)
                t2_utc = datetime.datetime.fromisoformat(end_time_raw)

                duration = t2_utc - t1_utc
                total_secs = int(duration.total_seconds())

                hours, rem = divmod(total_secs, 3600)
                mins, secs = divmod(rem, 60)
                ride["duration"] = f"{hours:02}:{mins:02}:{secs:02}"
                ride["start_str"] = t1_utc.astimezone(TIMEZONE).strftime(fmt)
            except ValueError:
                ride["duration"] = "Error"
        else:
            ride["duration"] = "Incomplete"

        ride["wind_arrow"] = get_wind_arrow(ride.get("wind_dir"))
        history.append(ride)

    return templates.TemplateResponse(
        request=request,
        name="partials/history_snippet.html",
        context={"rides": history},
    )


@router.post("/start")
async def start_ride(
    route: str = Form(...),
    direction: str = Form(...),
    extra_dist: bool = Form(False),
    db: sqlite3.Connection = Depends(get_db),
    auth=Depends(check_auth),
):
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
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


@router.post("/stop/{ride_id}")
async def stop_ride(
    ride_id: int, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    end_time = datetime.datetime.now(datetime.UTC).isoformat()
    db.execute("UPDATE rides SET end_time = ? WHERE id = ?", (end_time, ride_id))
    db.commit()
    return Response(headers={"HX-Refresh": "true"})


@router.post("/cancel/{ride_id}")
async def cancel_ride(
    ride_id: int, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    db.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
    db.commit()
    return Response(headers={"HX-Refresh": "true"})


@router.get("/recommend", response_class=HTMLResponse)
async def recommend(auth=Depends(check_auth)):
    recommendations = [
        ("A", "The winds are favorable for Route A today!"),
        ("A", "Route A has the least traffic right now."),
        ("B", "Route B is looking particularly scenic this morning."),
        ("B", "Route B is the fastest according to recent trends."),
        ("C", "There's a tailwind on Route C, take advantage of it!"),
        ("C", "Route C is the most sheltered from the current wind."),
    ]
    route, explanation = random.choice(recommendations)  # noqa S311

    return HTMLResponse(
        content=f"""
        <details open>
            <summary>Why this route?</summary>
            <p>{explanation}</p>
        </details>
        <script>selectOption('route', '{route}')</script>
    """
    )
