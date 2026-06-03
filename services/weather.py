import datetime
import email.utils
import logging

import httpx

from config import cache, settings

logger = logging.getLogger("biketracker.weather")


def get_wind_arrow(degrees):
    if degrees is None:
        return ""
    arrows = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    idx = int((degrees + 22.5) % 360 // 45)
    return arrows[idx]


async def fetch_nowcast(client: httpx.AsyncClient, url: str, headers: dict):
    n_headers = headers.copy()
    cached = cache.get(url)
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
        res = await client.get(url, headers=n_headers)
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
                url,
                {"data": res_json, "expires": exp_dt, "last_modified": lm_str},
            )
            return res_json
    except Exception:
        logger.exception("Error fetching nowcast data")

    return cached["data"] if cached else None


async def fetch_sun(client: httpx.AsyncClient, url: str, headers: dict):
    cached = cache.get(url)
    if cached:
        return cached

    try:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            res_json = res.json()
            cache.set(url, res_json, expire=86400)  # 24 hours
            return res_json
    except Exception:
        logger.exception("Error fetching sun data")
    return None
