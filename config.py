import logging
from zoneinfo import ZoneInfo
import diskcache
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("biketracker.config")

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
cache = diskcache.Cache(".cache")
