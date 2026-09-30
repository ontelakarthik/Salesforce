"""Unit tests for TwilioWhatsAppSender itself
(src/integrations/twilio_whatsapp.py) — below the level
tests/test_whatsapp_sending.py exercises, which overrides the whole
get_whatsapp_sender dependency with a fake and never reaches this class.
No network/DB access: httpx.post is monkeypatched so this never calls the
real Twilio API. Mirrors tests/test_sms_service.py exactly.
"""
import json
from unittest.mock import patch

import httpx

from src.integrations.twilio_whatsapp import TwilioContentTemplateSource, TwilioWhatsAppSender
from src.utils.exceptions import DomainError


def _response(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", "https://api.twilio.com/x"))


class TestWhatsAppPrefixing:
    def test_whatsapp_prefix_is_added_on_the_wire_but_never_returned(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(201, {"sid": "SMabc123"})) as mock_post:
            sid = sender.send("+15559998888", "Following up on your inquiry")

        assert sid == "SMabc123"
        data = mock_post.call_args.kwargs["data"]
        assert data["To"] == "whatsapp:+15559998888"
        assert data["From"] == "whatsapp:+15550001111"
        assert data["Body"] == "Following up on your inquiry"

    def test_no_status_callback_param_when_not_configured(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(201, {"sid": "SMabc123"})) as mock_post:
            sender.send("+15559998888", "Hi")
        assert "StatusCallback" not in mock_post.call_args.kwargs["data"]

    def test_status_callback_param_included_when_configured(self):
        sender = TwilioWhatsAppSender(
            "ACxxx", "tokenxxx", "+15550001111",
            status_callback_url="https://public.example.com/api/v1/whatsapp/webhook/status")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(201, {"sid": "SMabc123"})) as mock_post:
            sender.send("+15559998888", "Hi")
        assert mock_post.call_args.kwargs["data"]["StatusCallback"] == \
            "https://public.example.com/api/v1/whatsapp/webhook/status"


class TestTemplateSend:
    def test_template_send_uses_content_sid_and_json_variables_not_body(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(201, {"sid": "SMtpl123"})) as mock_post:
            sid = sender.send_template("+15559998888", "HXabc", {"1": "Priya", "2": "Q3 proposal"})

        assert sid == "SMtpl123"
        data = mock_post.call_args.kwargs["data"]
        assert data["To"] == "whatsapp:+15559998888"
        assert data["From"] == "whatsapp:+15550001111"
        assert data["ContentSid"] == "HXabc"
        assert json.loads(data["ContentVariables"]) == {"1": "Priya", "2": "Q3 proposal"}
        assert "Body" not in data

    def test_template_without_variables_omits_content_variables(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(201, {"sid": "SMtpl123"})) as mock_post:
            sender.send_template("+15559998888", "HXabc", {})
        assert "ContentVariables" not in mock_post.call_args.kwargs["data"]


def _get_response(json_body: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "https://content.twilio.com/x"))


class TestContentTemplateSource:
    def test_parses_templates_and_follows_pagination(self):
        page_1 = {"contents": [{
            "sid": "HX111", "friendly_name": "issue_resolution_v1", "language": "en",
            "variables": {"1": "name", "2": "ticket"},
            "types": {"twilio/text": {"body": "Hi {{1}}, ticket {{2}} is resolved."}},
            "approval_requests": {"name": "sample_issue_resolution", "category": "utility", "status": "approved"},
        }], "meta": {"next_page_url": "https://content.twilio.com/v1/ContentAndApprovals?Page=1"}}
        page_2 = {"contents": [{
            "sid": "HX222", "friendly_name": "promo", "language": "en_US", "variables": {},
            "types": {"twilio/quick-reply": {"body": "Big sale!", "actions": []}},
            "approval_requests": {"status": "unsubmitted"},
        }], "meta": {"next_page_url": None}}
        source = TwilioContentTemplateSource("ACxxx", "tokenxxx")
        with patch("src.integrations.twilio_whatsapp.httpx.get",
                  side_effect=[_get_response(page_1), _get_response(page_2)]) as mock_get:
            templates = source.fetch_templates()

        assert mock_get.call_count == 2
        first, second = templates
        assert (first.content_sid, first.name, first.category, first.approval_status) == \
            ("HX111", "sample_issue_resolution", "UTILITY", "APPROVED")
        assert first.body_preview == "Hi {{1}}, ticket {{2}} is resolved."
        assert first.variable_count == 2
        # No WhatsApp approval request yet -> falls back to friendly_name, and can't be sent.
        assert (second.name, second.category, second.approval_status, second.variable_count) == \
            ("promo", "UNCATEGORIZED", "PENDING", 0)
        assert second.body_preview == "Big sale!"

    def test_non_2xx_listing_raises_502(self):
        source = TwilioContentTemplateSource("ACxxx", "tokenxxx")
        with patch("src.integrations.twilio_whatsapp.httpx.get",
                  return_value=_get_response({"message": "Authenticate"}, status_code=401)):
            try:
                source.fetch_templates()
                assert False, "expected DomainError"
            except DomainError as exc:
                assert exc.status_code == 502
                assert exc.code == "WHATSAPP_TEMPLATE_SYNC_FAILED"
                assert "Authenticate" in exc.message


class TestErrorHandling:
    def test_non_2xx_twilio_response_raises_502_with_twilio_message(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post",
                  return_value=_response(400, {"message": "Invalid 'To' Phone Number"})):
            try:
                sender.send("not-a-number", "Hi")
                assert False, "expected DomainError"
            except DomainError as exc:
                assert exc.status_code == 502
                assert "Invalid 'To' Phone Number" in exc.message

    def test_network_failure_raises_502(self):
        sender = TwilioWhatsAppSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.integrations.twilio_whatsapp.httpx.post", side_effect=httpx.ConnectTimeout("timed out")):
            try:
                sender.send("+15559998888", "Hi")
                assert False, "expected DomainError"
            except DomainError as exc:
                assert exc.status_code == 502


class TestGetWhatsAppSender:
    def test_raises_503_when_not_configured(self, monkeypatch):
        from src.config.config_reader import get_settings
        from src.integrations.twilio_whatsapp import get_whatsapp_sender

        settings = get_settings()
        monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", None)
        monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", None)
        monkeypatch.setattr(settings, "TWILIO_WHATSAPP_FROM", None)
        try:
            get_whatsapp_sender()
            assert False, "expected DomainError"
        except DomainError as exc:
            assert exc.status_code == 503
            assert exc.code == "WHATSAPP_PROVIDER_NOT_CONFIGURED"
