"""Unit tests for the Twilio Voice integration layer
(src/integrations/twilio_voice.py) — Access Token minting, TwiML building,
and the Twilio-status -> CRM call_disposition mapping. Pure local
computation (Access Tokens are signed locally, never fetched from Twilio),
so no network/DB access anywhere in this file.
"""
import jwt

from src.integrations import twilio_voice
from src.utils.exceptions import DomainError


class TestMintAccessToken:
    def test_token_has_correct_claims_and_header(self, monkeypatch):
        from src.config.config_reader import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC1234567890")
        monkeypatch.setattr(settings, "TWILIO_VOICE_API_KEY_SID", "SKvoice123")
        monkeypatch.setattr(settings, "TWILIO_VOICE_API_KEY_SECRET", "supersecretkeysupersecretkey")
        monkeypatch.setattr(settings, "TWILIO_VOICE_TWIML_APP_SID", "APvoice123")

        token = twilio_voice.mint_access_token(identity="employee-1")

        header = jwt.get_unverified_header(token)
        assert header["cty"] == "twilio-fpa;v=1"
        assert header["alg"] == "HS256"

        claims = jwt.decode(token, "supersecretkeysupersecretkey", algorithms=["HS256"])
        assert claims["iss"] == "SKvoice123"
        assert claims["sub"] == "AC1234567890"
        assert claims["grants"]["identity"] == "employee-1"
        assert claims["grants"]["voice"]["outgoing"]["application_sid"] == "APvoice123"
        assert claims["grants"]["voice"]["incoming"]["allow"] is False

    def test_raises_503_when_not_configured(self, monkeypatch):
        from src.config.config_reader import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", None)
        monkeypatch.setattr(settings, "TWILIO_VOICE_API_KEY_SID", None)
        monkeypatch.setattr(settings, "TWILIO_VOICE_API_KEY_SECRET", None)
        monkeypatch.setattr(settings, "TWILIO_VOICE_TWIML_APP_SID", None)
        try:
            twilio_voice.mint_access_token(identity="x")
            assert False, "expected DomainError"
        except DomainError as exc:
            assert exc.status_code == 503
            assert exc.code == "VOICE_PROVIDER_NOT_CONFIGURED"


class TestBuildConnectTwiml:
    def test_dials_the_number_with_caller_id_and_status_callback(self):
        xml = twilio_voice.build_connect_twiml(
            to_number="+15551234567", caller_id="+17370000000",
            status_callback_url="https://public.example.com/api/v1/voice/webhook/status")
        assert '<Dial callerId="+17370000000">' in xml
        assert "+15551234567</Number>" in xml
        assert 'statusCallback="https://public.example.com/api/v1/voice/webhook/status"' in xml
        assert 'statusCallbackEvent="initiated ringing answered completed"' in xml

    def test_omits_status_callback_attrs_when_not_configured(self):
        xml = twilio_voice.build_connect_twiml(to_number="+15551234567", caller_id="+1", status_callback_url=None)
        assert "statusCallback" not in xml

    def test_escapes_the_phone_number(self):
        xml = twilio_voice.build_connect_twiml(to_number="+1555<hack>&", caller_id="+1", status_callback_url=None)
        assert "<hack>" not in xml
        assert "&amp;" in xml or "&lt;" in xml


class TestCallStatusMapping:
    def test_terminal_statuses_map_to_existing_call_disposition_codes(self):
        assert twilio_voice.map_call_status_to_disposition_code("completed") == "CONNECTED"
        assert twilio_voice.map_call_status_to_disposition_code("busy") == "BUSY"
        assert twilio_voice.map_call_status_to_disposition_code("no-answer") == "NO_ANSWER"
        assert twilio_voice.map_call_status_to_disposition_code("failed") == "OTHER"
        assert twilio_voice.map_call_status_to_disposition_code("canceled") == "OTHER"

    def test_non_terminal_statuses_map_to_nothing(self):
        assert twilio_voice.map_call_status_to_disposition_code("initiated") is None
        assert twilio_voice.map_call_status_to_disposition_code("ringing") is None
        assert twilio_voice.map_call_status_to_disposition_code("in-progress") is None

    def test_friendly_error_message_for_known_and_unknown_codes(self):
        assert "verified" in twilio_voice.friendly_error_message("21215").lower()
        assert twilio_voice.friendly_error_message("00000") is None
        assert twilio_voice.friendly_error_message(None) is None
