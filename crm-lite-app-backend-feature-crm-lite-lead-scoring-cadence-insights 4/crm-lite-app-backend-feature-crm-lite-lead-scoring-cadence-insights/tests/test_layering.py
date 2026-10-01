"""Architecture guardrails: enforce clean layering. Route handlers (src/server/)
must not touch the ORM/DB layer directly; services/models must not import them.

Pydantic request/response schemas live alongside the ORM class in
models/<module>_models.py (see models/crm_models.py), so route modules
importing e.g. `crm_models.AccountOut` for response_model= is expected
and allowed — that's "shape the response" per CLAUDE.md. What route modules
must still not do is reach past the service/repository layer into the ORM Base
class or SQLAlchemy itself. There is no separate routers/ package — routes
live directly in src/server/ alongside the app-assembly __init__.py.
"""
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


def _read(*parts):
    return (SRC.joinpath(*parts)).read_text()


def _route_files():
    return [f for f in (SRC / "server").glob("*.py") if f.name != "__init__.py"]


def test_route_modules_do_not_import_orm_directly():
    for f in _route_files():
        txt = f.read_text()
        assert "src.models.base" not in txt, f"{f.name} imports the ORM Base directly"
        assert "sqlalchemy" not in txt.lower(), f"{f.name} imports SQLAlchemy directly"


def test_services_do_not_import_server():
    for f in (SRC / "services").glob("*.py"):
        assert "src.server" not in f.read_text(), f"{f.name} imports the server/route layer"


def test_models_do_not_import_server_or_services():
    for f in (SRC / "models").glob("*.py"):
        txt = f.read_text()
        assert "src.server" not in txt and "src.services" not in txt
