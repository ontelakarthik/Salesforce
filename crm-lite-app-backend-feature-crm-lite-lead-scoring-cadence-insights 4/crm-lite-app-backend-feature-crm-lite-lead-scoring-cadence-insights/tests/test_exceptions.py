"""Error-handling contract: what the console shows and what the UI receives.

The core guarantee these tests protect is that a server-side failure produces
ONE message string used in both places (log + response body), tied to a
correlation id — so a user's report can always be matched to a stack trace.
"""
import logging

import pytest
from fastapi.testclient import TestClient

from src.server import app
from src.utils.error_handling import handle_errors
from src.utils.exceptions import DomainError


class TestHandleErrors:
    def test_domain_error_passes_through_untouched(self):
        @handle_errors("do the thing")
        def fn():
            raise DomainError("ACCOUNT_NOT_FOUND", "No account 'X'.", 404)

        with pytest.raises(DomainError) as excinfo:
            fn()
        assert excinfo.value.code == "ACCOUNT_NOT_FOUND"
        assert excinfo.value.status_code == 404
        assert excinfo.value.message == "No account 'X'."

    def test_unexpected_error_becomes_500_naming_operation_and_cause(self):
        @handle_errors("promote the account")
        def fn():
            raise RuntimeError("psycopg connection refused")

        with pytest.raises(DomainError) as excinfo:
            fn()
        err = excinfo.value
        assert err.code == "INTERNAL_ERROR"
        assert err.status_code == 500
        assert err.message == (
            "Couldn't promote the account because of a server error: "
            "psycopg connection refused")
        assert isinstance(err.__cause__, RuntimeError)  # original kept for the traceback

    def test_logged_message_is_identical_to_the_one_returned(self, caplog):
        """The whole point of the shared string: if these two ever drift, a
        user-reported message can no longer be grepped for in the logs."""
        @handle_errors("save the SOW details")
        def fn():
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(DomainError) as excinfo:
                fn()

        record = next(r for r in caplog.records if r.levelno == logging.ERROR)
        assert record.getMessage() == excinfo.value.message
        assert record.exc_info is not None, "stack trace must be attached"

    def test_return_value_and_metadata_survive_decoration(self):
        @handle_errors("compute")
        def fn(a, b=2):
            """docstring."""
            return a + b

        assert fn(1) == 3
        assert fn(1, b=10) == 11
        assert fn.__name__ == "fn"
        assert fn.__doc__ == "docstring."


class TestProductionHidesInternals:
    """In prod the exception text is logged but must not reach the client —
    it can carry a DB host, a failing SQL statement, or a file path. The
    correlation id replaces it as the link back to the stack trace."""

    @pytest.fixture
    def in_production(self, monkeypatch):
        from src.config.config_reader import settings
        monkeypatch.setattr(settings, "APP_ENV", "prod")

    def test_client_message_omits_exception_text_but_log_keeps_it(
            self, in_production, caplog):
        @handle_errors("load the dashboard")
        def fn():
            raise RuntimeError("password=hunter2 host=prod-db.internal")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(DomainError) as excinfo:
                fn()

        client_message = excinfo.value.message
        assert "hunter2" not in client_message
        assert "prod-db.internal" not in client_message
        assert client_message.startswith(
            "Couldn't load the dashboard because of a server error.")

        logged = next(r for r in caplog.records if r.levelno == logging.ERROR)
        assert "password=hunter2 host=prod-db.internal" in logged.getMessage()
        assert logged.exc_info is not None

    def test_client_message_carries_the_correlation_id_for_support(
            self, in_production):
        from src.utils.request_context import set_request_id

        set_request_id("prod-incident-77")

        @handle_errors("save the SOW details")
        def fn():
            raise ValueError("boom")

        with pytest.raises(DomainError) as excinfo:
            fn()
        assert "prod-incident-77" in excinfo.value.message

    def test_unhandled_handler_is_gated_too(self, in_production):
        @app.get("/api/v1/__test_prod_boom")
        def _boom():
            raise RuntimeError("host=prod-db.internal")

        try:
            local_client = TestClient(app, raise_server_exceptions=False)
            r = local_client.get("/api/v1/__test_prod_boom",
                                 headers={"X-Request-Id": "prod-boom-1"})
            assert r.status_code == 500
            body = r.json()["error"]
            assert "prod-db.internal" not in body["message"]
            assert body["request_id"] == "prod-boom-1"
        finally:
            app.router.routes = [
                route for route in app.router.routes
                if getattr(route, "path", None) != "/api/v1/__test_prod_boom"]
            app.openapi_schema = None


class TestErrorEnvelope:
    def test_correlation_id_is_echoed_in_body_and_header(self, client):
        r = client.get("/api/v1/accounts/NOPE-00000",
                       headers={"X-Request-Id": "trace-me-123"})
        assert r.status_code == 404
        assert r.json()["error"]["request_id"] == "trace-me-123"
        assert r.headers["X-Request-Id"] == "trace-me-123"

    def test_correlation_id_is_generated_when_client_sends_none(self, client):
        r = client.get("/api/v1/accounts/NOPE-00000")
        assert r.status_code == 404
        assert r.json()["error"]["request_id"] == r.headers["X-Request-Id"]

    def test_validation_error_keeps_field_details(self, client):
        r = client.post("/api/v1/accounts", json={})   # legal_name is required
        assert r.status_code == 422
        body = r.json()["error"]
        assert body["code"] == "VALIDATION_ERROR"
        assert body["fields"], "field-level errors must survive for form display"

    def test_unhandled_exception_returns_the_envelope_not_a_bare_500(self, caplog):
        """Safety net for a bug outside a decorated service function — it must
        still be logged with a trace and answered with a readable envelope."""
        @app.get("/api/v1/__test_boom")
        def _boom():
            raise RuntimeError("simulated bug")

        try:
            local_client = TestClient(app, raise_server_exceptions=False)
            with caplog.at_level(logging.ERROR):
                r = local_client.get("/api/v1/__test_boom",
                                     headers={"X-Request-Id": "boom-1"})
            assert r.status_code == 500
            body = r.json()["error"]
            assert body["code"] == "INTERNAL_ERROR"
            assert body["message"] == (
                "Couldn't complete the request because of a server error: simulated bug")
            assert body["request_id"] == "boom-1"

            record = next(r for r in caplog.records if r.levelno == logging.ERROR)
            assert record.getMessage() == body["message"]
            assert record.exc_info is not None
        finally:
            # Route table is app-global; leaving it behind would change the
            # endpoint count other tests assert on.
            app.router.routes = [
                route for route in app.router.routes
                if getattr(route, "path", None) != "/api/v1/__test_boom"]
            app.openapi_schema = None


class TestServiceFunctionsAreDecorated:
    def test_every_service_function_called_by_a_route_is_wrapped(self):
        """Guards the convention itself: a new endpoint whose service function
        forgets @handle_errors would return an unlogged, generic 500."""
        import importlib
        import inspect
        import pkgutil
        import re

        import src.server as server_pkg

        called: set[tuple[str, str]] = set()
        pattern = re.compile(r"\b(\w+_service)\.(\w+)\s*\(")
        for module_info in pkgutil.iter_modules(server_pkg.__path__):
            if not module_info.name.endswith("_routes"):
                continue
            module = importlib.import_module(f"src.server.{module_info.name}")
            called.update(pattern.findall(inspect.getsource(module)))

        assert called, "expected to find service calls in the route modules"

        undecorated = []
        for service_name, fn_name in sorted(called):
            service = importlib.import_module(f"src.services.{service_name}")
            fn = getattr(service, fn_name, None)
            if fn is None or not callable(fn):
                continue
            if not hasattr(fn, "__wrapped__"):
                undecorated.append(f"{service_name}.{fn_name}")

        assert not undecorated, (
            "missing @handle_errors on: " + ", ".join(undecorated))
