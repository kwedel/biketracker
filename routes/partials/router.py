import datetime
import random
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from config import TIMEZONE
from core import (
    check_auth,
    get_db,
    get_departure_data,
    templates,
)
from services.weather import get_wind_arrow

router = APIRouter()


def _render_history(request: Request, db: sqlite3.Connection) -> str:
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

    template = templates.get_template("partials/history_snippet.html")
    return template.render(request=request, rides=history)


@router.get("/history", response_class=HTMLResponse)
async def get_history(
    request: Request, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    history_html = _render_history(request, db)
    return HTMLResponse(content=history_html)


def _utc_to_local_str(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        t_utc = datetime.datetime.fromisoformat(iso_str)
        if t_utc.tzinfo is None:
            t_utc = t_utc.replace(tzinfo=datetime.UTC)
        return t_utc.astimezone(TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ""


def _local_to_utc_str(local_str: str) -> str:
    try:
        dt_naive = datetime.datetime.fromisoformat(local_str)
        dt_local = dt_naive.replace(tzinfo=TIMEZONE)
        dt_utc = dt_local.astimezone(datetime.UTC)
        return dt_utc.isoformat(timespec="seconds")
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid datetime format") from e


@router.get("/rides/{ride_id}/edit", response_class=HTMLResponse)
async def edit_ride_get(
    ride_id: int,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    auth=Depends(check_auth)
):
    ride = db.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    ride_dict = dict(ride)
    start_time_local = _utc_to_local_str(ride_dict.get("start_time"))
    end_time_local = _utc_to_local_str(ride_dict.get("end_time"))

    return templates.TemplateResponse(
        request=request,
        name="partials/edit_modal.html",
        context={
            "ride": ride_dict,
            "start_time_local": start_time_local,
            "end_time_local": end_time_local,
        }
    )


@router.post("/rides/{ride_id}/edit", response_class=HTMLResponse)
async def edit_ride_post(
    ride_id: int,
    request: Request,
    start_time: str = Form(...),
    end_time: str = Form(...),
    route: str = Form(...),
    direction: str = Form(...),
    extra_dist: bool = Form(False),
    db: sqlite3.Connection = Depends(get_db),
    auth=Depends(check_auth)
):
    ride = db.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    start_time_utc_str = _local_to_utc_str(start_time)
    end_time_utc_str = _local_to_utc_str(end_time)

    db.execute(
        """
        UPDATE rides
        SET start_time = ?, end_time = ?, route = ?, direction = ?, extra_dist = ?
        WHERE id = ?
        """,
        (
            start_time_utc_str,
            end_time_utc_str,
            route,
            direction,
            1 if extra_dist else 0,
            ride_id
        )
    )
    db.commit()

    history_html = _render_history(request, db)
    response_html = f'{history_html}\n<div id="modal-container" hx-swap-oob="true"></div>'
    return HTMLResponse(content=response_html)


@router.delete("/rides/{ride_id}/delete", response_class=HTMLResponse)
async def delete_ride(
    ride_id: int,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    auth=Depends(check_auth)
):
    ride = db.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    db.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
    db.commit()

    history_html = _render_history(request, db)
    response_html = f'{history_html}\n<div id="modal-container" hx-swap-oob="true"></div>'
    return HTMLResponse(content=response_html)


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
async def recommend(request: Request, auth=Depends(check_auth)):
    recommendations = [
        ("A", "The winds are favorable for Route A today!"),
        ("A", "Route A has the least traffic right now."),
        ("B", "Route B is looking particularly scenic this morning."),
        ("B", "Route B is the fastest according to recent trends."),
        ("C", "There's a tailwind on Route C, take advantage of it!"),
        ("C", "Route C is the most sheltered from the current wind."),
    ]
    route, explanation = random.choice(recommendations)  # noqa S311

    weather = await get_departure_data()
    wind_arrow = get_wind_arrow(weather.get("w_dir"))

    return templates.TemplateResponse(
        request=request,
        name="partials/recommendation.html",
        context={
            "request": request,
            "weather": weather,
            "wind_arrow": wind_arrow,
            "route": route,
            "explanation": explanation,
        },
    )
