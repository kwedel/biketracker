import logging

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from core import init_db
from routes.pages.router import router as pages_router
from routes.partials.router import router as partials_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("biketracker").setLevel(settings.loglevel)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.session_key)

# Include routers
app.include_router(pages_router)
app.include_router(partials_router)


@app.on_event("startup")
async def startup_event():
    init_db()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
