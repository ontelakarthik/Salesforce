"""FastAPI application factory + entry point (the "server").

Single assembly point: health + the 8 spec-defined service route modules are
mounted here (§1 of the API spec: Auth & RBAC, CRM, Contracts, Delivery,
Projects, Activity, Admin, Platform). One route file per module keeps
merge-conflict surface low and makes it obvious where a given endpoint lives —
there is no separate routers/ or schemas/ package; routes live in this folder,
request/response schemas live alongside each module's ORM class in src/models/.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from swagger_ui_bundle import swagger_ui_path

from src.config.config_reader import settings
from src.server import (
    activity_routes,
    admin_routes,
    auth_routes,
    contracts_routes,
    crm_routes,
    delivery_routes,
    health,
    platform_routes,
    project_routes,
)
from src.utils.exceptions import install_error_handlers
from src.utils.logging_config import configure_logging
from src.utils.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Contract Lifecycle Management — business services (skeleton).",
        docs_url=None,  # replaced below with a CDN-free Swagger UI (see /docs)
    )
    # swagger_ui_bundle (used below for offline docs) ships Swagger UI 4.15.5,
    # which predates OpenAPI 3.1 support and rejects FastAPI's default
    # "openapi": "3.1.0" schema with "Unable to render this definition".
    # 3.0.2 is close enough in shape that Swagger UI 4.x renders it correctly.
    app.openapi_version = "3.0.2"
    app.add_middleware(RequestContextMiddleware)
    # No gateway in front anymore — this service is the browser-facing entry
    # point directly, so it owns CORS itself (settings.CORS_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    install_error_handlers(app)

    # Default /docs pulls its JS/CSS from cdn.jsdelivr.net, which hangs
    # forever on networks that block it (common on locked-down corporate
    # machines). Serve the same Swagger UI from locally vendored static
    # files instead (swagger_ui_bundle) so /docs works fully offline.
    app.mount("/swagger-ui-assets", StaticFiles(directory=str(swagger_ui_path)), name="swagger-ui-assets")

    @app.get("/docs", include_in_schema=False)
    def swagger_ui():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} — Swagger UI",
            swagger_js_url="/swagger-ui-assets/swagger-ui-bundle.js",
            swagger_css_url="/swagger-ui-assets/swagger-ui.css",
            swagger_favicon_url="/swagger-ui-assets/favicon-32x32.png",
        )

    app.include_router(health.router)                                    # /health
    app.include_router(auth_routes.router, prefix=settings.API_PREFIX)
    app.include_router(crm_routes.router, prefix=settings.API_PREFIX)
    app.include_router(contracts_routes.router, prefix=settings.API_PREFIX)
    app.include_router(delivery_routes.router, prefix=settings.API_PREFIX)
    app.include_router(project_routes.router, prefix=settings.API_PREFIX)
    app.include_router(activity_routes.router, prefix=settings.API_PREFIX)
    app.include_router(admin_routes.router, prefix=settings.API_PREFIX)
    app.include_router(platform_routes.router, prefix=settings.API_PREFIX)
    return app


app = create_app()
