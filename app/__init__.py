"""FastAPI application factory.

Each feature declares its own URLs with an APIRouter next to its views;
create_app() includes them all. The JSON APIs are documented at /docs.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.camera import status_page as camera_status
from app.camera import views as camera
from app.camera.capture import CaptureService
from app.camera.health import CameraMonitor
from app.camera.schedule import start_scheduler, stop_scheduler
from app.camera.worker import CountingWorker, store_and_queue
from app.config import load_settings
from app.database.connection import create_database_engine, make_session_factory
from app.forecast import model as forecast_model
from app.forecast import views as forecast
from app.reports import views as reports
from app.reports.schedule import start_report_scheduler, stop_report_scheduler
from app.vision import counting, meal_check
from app.waste_records import add_record, edit_record, food_prices, overview
from app.web import RequestSizeLimit, install_error_handlers, templates


ROUTERS = (
    auth.router,                                                                  # sign in and out
    overview.router, add_record.router, edit_record.router, food_prices.router,   # waste records and prices
    forecast.router,                                                              # meal forecast
    reports.router,                                                               # weekly email report
    counting.router, meal_check.router,                                           # food counting
    camera.router, camera_status.router,                                          # camera captures and status
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start counting captured photos and the capture scheduler with the server; stop them with it."""
    if not app.state.settings.get("TESTING"):
        app.state.counting_worker.start()
    start_scheduler(app)
    start_report_scheduler(app)
    try:
        yield
    finally:
        stop_scheduler(app)
        stop_report_scheduler(app)
        app.state.counting_worker.stop()


def create_app(config=None) -> FastAPI:
    settings = load_settings(config)
    app = FastAPI(
        lifespan=lifespan,
        title="Wastewise",
        summary="Hotel food waste records, meal demand forecasts and food recognition.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    templates.env.globals["CURRENCY_SYMBOL"] = settings["CURRENCY_SYMBOL"]
    app.state.capture_service = CaptureService(settings)
    app.state.counting_worker = CountingWorker(app)
    app.state.camera_monitor = CameraMonitor(app)

    def on_capture(event):
        try:
            app.state.camera_monitor.record_event(event)   # a camera that gave no photo is reported offline
        except Exception:
            logging.getLogger(__name__).exception("Could not record the camera status.")
        return store_and_queue(app, event)

    app.state.capture_service.on_event = on_capture
    app.state.engine = create_database_engine(settings["DATABASE_URL"])
    app.state.session_factory = make_session_factory(app.state.engine)
    forecast_model.init_app(app)

    app.state.login_limiter = auth.AttemptLimiter(settings["LOGIN_MAX_ATTEMPTS"], settings["LOGIN_LOCK_MINUTES"])
    app.add_middleware(RequestSizeLimit)
    # Added last = runs first: the session cookie is read before the access check needs it.
    app.add_middleware(BaseHTTPMiddleware, dispatch=auth.require_sign_in)
    app.add_middleware(SessionMiddleware, secret_key=settings["SECRET_KEY"], session_cookie="wastewise_session",
                       max_age=settings["REMEMBER_DAYS"] * 86400, same_site="lax", https_only=False)
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    for router in ROUTERS:
        app.include_router(router)
    return app
