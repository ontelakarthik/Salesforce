"""Unit tests for TwilioSmsSender itself (src/services/sms_service.py) —
below the level tests/test_sms_sending.py exercises, which overrides the
whole get_sms_sender dependency with a fake and never reaches this class.
No network/DB access: httpx.post is monkeypatched so this never calls the
real Twilio API.
"""
from unittest.mock import patch

import httpx

from src.services.sms_service import TwilioSmsSender
from src.utils.exceptions import DomainError


def _response(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", "https://api.twilio.com/x"))


class TestSenderPrefix:
    def test_wire_body_is_prefixed_with_crm_lite_but_returned_sid_is_untouched(self):
        sender = TwilioSmsSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.services.sms_service.httpx.post",
                  return_value=_response(201, {"sid": "SMabc123"})) as mock_post:
            sid = sender.send("+15559998888", "Following up on your inquiry")

        assert sid == "SMabc123"
        sent_body = mock_post.call_args.kwargs["data"]["Body"]
        assert sent_body == "CRM Lite: Following up on your inquiry"
        assert mock_post.call_args.kwargs["data"]["To"] == "+15559998888"
        assert mock_post.call_args.kwargs["data"]["From"] == "+15550001111"


class TestErrorHandling:
    def test_non_2xx_twilio_response_raises_502_with_twilio_message(self):
        sender = TwilioSmsSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.services.sms_service.httpx.post",
                  return_value=_response(400, {"message": "Invalid 'To' Phone Number"})):
            try:
                sender.send("not-a-number", "Hi")
                assert False, "expected DomainError"
            except DomainError as exc:
                assert exc.status_code == 502
                assert "Invalid 'To' Phone Number" in exc.message

    def test_network_failure_raises_502(self):
        sender = TwilioSmsSender("ACxxx", "tokenxxx", "+15550001111")
        with patch("src.services.sms_service.httpx.post", side_effect=httpx.ConnectTimeout("timed out")):
            try:
                sender.send("+15559998888", "Hi")
                assert False, "expected DomainError"
            except DomainError as exc:
                assert exc.status_code == 502
