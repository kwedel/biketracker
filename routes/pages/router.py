import datetime
import hmac
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core import TIMEZONE, check_auth, get_db, settings, templates
from routes.pages.analytics import get_dashboard_data

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/login.html",
        context={"request": request},
    )


@router.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if hmac.compare_digest(password, settings.USER_PASSWORD):
        request.session["logged_in"] = True
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, db: sqlite3.Connection = Depends(get_db), auth=Depends(check_auth)
):
    active = db.execute("SELECT * FROM rides WHERE end_time IS NULL LIMIT 1").fetchone()
    if active:
        local_start_time = (
            datetime.datetime.fromisoformat(active["start_time"])
            .astimezone(TIMEZONE)
            .time()
            .isoformat("seconds")
        )
    else:
        local_start_time = None

    return templates.TemplateResponse(
        request=request,
        name="pages/index.html",
        context={
            "request": request,
            "active_ride": active,
            "local_start_time": local_start_time,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, auth=Depends(check_auth)):
    chart_json, stats = get_dashboard_data(settings.DB_PATH)
    return templates.TemplateResponse(
        request=request,
        name="pages/dashboard.html",
        context={"request": request, "chart_json": chart_json, "stats": stats},
    )
