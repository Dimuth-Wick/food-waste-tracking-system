"""FastAPI application factory.

Each feature declares its own URLs with an APIRouter next to its views;
create_app() includes them all. The JSON APIs are documented at /docs.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.database.connection import create_database_engine, make_session_factory
from app.forecast import model as forecast_model
from app.forecast import views as forecast
from app.vision import counting
from app.waste_records import add_record, edit_record, overview
from app.web import RequestSizeLimit, install_error_handlers


ROUTERS = (
    overview.router, add_record.router, edit_record.router,                       # waste records
    forecast.router,                                                              # meal forecast
    counting.router,                                                              # food counting
)


def create_app(config=None) -> FastAPI:
    settings = load_settings(config)
    app = FastAPI(
        title="Wastewise",
        summary="Hotel food waste records, meal demand forecasts and food recognition.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = create_database_engine(settings["DATABASE_URL"])
    app.state.session_factory = make_session_factory(app.state.engine)
    forecast_model.init_app(app)

    app.add_middleware(RequestSizeLimit)
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    for router in ROUTERS:
        app.include_router(router)
    return app
