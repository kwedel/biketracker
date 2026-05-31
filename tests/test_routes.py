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
