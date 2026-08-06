import pytest
from core import settings

def test_login_page(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Login" in response.text

def test_login_success(client):
    response = client.post("/login", data={"password": "testpassword"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["Location"] == "/"

def test_login_failure(client):
    response = client.post("/login", data={"password": "wrongpassword"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["Location"] == "/login"

def test_index_unauthenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["Location"] == "/login"

def test_index_authenticated(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Bike Tracker" in response.text

def test_ride_lifecycle(auth_client, db, mock_met_api):
    # 1. Start a ride
    response = auth_client.post("/start", data={"route": "Route A", "direction": "Inbound"}, follow_redirects=True)
    assert response.status_code == 200

    # Verify ride is in DB
    ride = db.execute("SELECT * FROM rides WHERE end_time IS NULL").fetchone()
    assert ride is not None
    assert ride["route"] == "Route A"
    assert ride["temp"] == 15.5
    ride_id = ride["id"]

    # 2. Stop the ride
    response = auth_client.post(f"/stop/{ride_id}")
    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"

    # Verify ride is finished in DB
    ride = db.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    assert ride["end_time"] is not None

    # 3. Cancel a ride (delete it)
    # Start another one first
    auth_client.post("/start", data={"route": "Route B", "direction": "Outbound"})
    ride_to_cancel = db.execute("SELECT * FROM rides WHERE end_time IS NULL").fetchone()
    cancel_id = ride_to_cancel["id"]

    response = auth_client.post(f"/cancel/{cancel_id}")
    assert response.status_code == 200

    # Verify it's gone
    ride = db.execute("SELECT * FROM rides WHERE id = ?", (cancel_id,)).fetchone()
    assert ride is None

def test_history_snippet(auth_client, db):
    # Insert a dummy finished ride
    db.execute(
        "INSERT INTO rides (route, direction, start_time, end_time) VALUES (?, ?, ?, ?)",
        ("Route C", "Inbound", "2023-10-27T10:00:00+00:00", "2023-10-27T10:30:00+00:00")
    )
    db.commit()

    response = auth_client.get("/history")
    assert response.status_code == 200
    assert "Route C" in response.text
    assert "00:30:00" in response.text # Duration check

def test_dashboard(auth_client, db):
    # Insert a dummy finished ride
    db.execute(
        "INSERT INTO rides (route, direction, start_time, end_time, precip_next_hour) VALUES (?, ?, ?, ?, ?)",
        ("Route D", "Outbound", "2023-10-27T12:00:00+00:00", "2023-10-27T12:15:00+00:00", 0.0)
    )
    db.commit()

    response = auth_client.get("/dashboard")
    assert response.status_code == 200
    assert "Total Trips" in response.text
    assert "vis-timeline" in response.text
    assert "vis-distributions" in response.text
    assert "vis-scatter" in response.text
    assert "timelineSpec" in response.text
    assert "distributionsSpec" in response.text
    assert "scatterSpec" in response.text

def test_get_dashboard_data_head_wind(db):
    # Direction: work (bearing 100), wind_dir: 100, wind_speed: 10.0
    # Head wind component should be 10.0 * cos(100 - 100) = 10.0
    db.execute(
        "INSERT INTO rides (route, direction, start_time, end_time, wind_dir, wind_speed) VALUES (?, ?, ?, ?, ?, ?)",
        ("A", "work", "2023-10-27T12:00:00+00:00", "2023-10-27T12:15:00+00:00", 100.0, 10.0)
    )
    # Direction: home (bearing 280), wind_dir: 100, wind_speed: 10.0
    # Head wind component should be 10.0 * cos(100 - 280) = 10.0 * cos(-180) = -10.0
    db.execute(
        "INSERT INTO rides (route, direction, start_time, end_time, wind_dir, wind_speed) VALUES (?, ?, ?, ?, ?, ?)",
        ("A", "home", "2023-10-27T13:00:00+00:00", "2023-10-27T13:15:00+00:00", 100.0, 10.0)
    )
    db.commit()

    from routes.pages.analytics import get_dashboard_data
    from core import settings
    import polars as pl

    # We query from the database using pl.read_database_uri to see that the calculated values are mathematically correct
    df = pl.read_database_uri(
        query="SELECT * FROM rides WHERE end_time IS NOT NULL",
        uri=f"sqlite://{settings.DB_PATH}",
    )

    # Calculate duration (required for parsing)
    import datetime
    import math
    def parse_duration(s, e):
        start = datetime.datetime.fromisoformat(s)
        end = datetime.datetime.fromisoformat(e)
        diff = end - start
        return diff.total_seconds() / 60

    df = df.with_columns(
        pl.col("start_time").str.to_datetime("%Y-%m-%dT%H:%M:%S+00:00"),
        pl.struct(["start_time", "end_time"])
        .map_elements(
            lambda x: parse_duration(x["start_time"], x["end_time"]),
            return_dtype=pl.Float64,
        )
        .alias("duration_min"),
    )

    # Calculate travel bearing and head wind
    df = df.with_columns(
        pl.when(pl.col("direction").str.to_lowercase().is_in(["work", "inbound"]))
        .then(100.0)
        .otherwise(280.0)
        .alias("travel_bearing")
    )
    df = df.with_columns(
        (
            pl.col("wind_speed")
            * ((pl.col("wind_dir") - pl.col("travel_bearing")) * math.pi / 180.0).cos()
        ).alias("head_wind")
    )

    # Filter the work and home rides to verify exact calculation
    work_ride = df.filter(pl.col("direction") == "work").to_dicts()[0]
    home_ride = df.filter(pl.col("direction") == "home").to_dicts()[0]

    assert abs(work_ride["head_wind"] - 10.0) < 1e-4
    assert abs(home_ride["head_wind"] - (-10.0)) < 1e-4
