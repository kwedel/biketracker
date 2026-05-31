import os
import sqlite3
import pytest
from fastapi.testclient import TestClient
from main import app
from core import settings, init_db

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    # Use a test database
    settings.DB_PATH = "test_bike_rides.db"
    settings.USER_PASSWORD = "testpassword"

    # Initialize the test database
    init_db()

    yield

    # Clean up after all tests
    if os.path.exists(settings.DB_PATH):
        os.remove(settings.DB_PATH)

@pytest.fixture
def db():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_client(client):
    # Log in the client
    client.post("/login", data={"password": "testpassword"})
    return client

@pytest.fixture
def mock_met_api(mocker):
    mock_data = {
        "temp": 15.5,
        "precip_instant": 0.0,
        "precip_next_hour": 0.0,
        "hum": 60.0,
        "w_dir": 180.0,
        "w_spd": 5.0,
        "w_gst": 7.0,
        "symbol": "clearsky_day",
        "sunrise": "2023-10-27T06:00:00Z",
        "sunset": "2023-10-27T18:00:00Z",
    }
    return mocker.patch("routes.partials.router.get_departure_data", return_value=mock_data)
