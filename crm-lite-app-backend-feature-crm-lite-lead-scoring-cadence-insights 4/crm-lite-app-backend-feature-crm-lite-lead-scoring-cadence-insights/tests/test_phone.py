"""utils/phone.normalize_phone() and its use on Lead create/update — no DB.

Regression for a lead stored as "+91 7330671971": Twilio (trial) rejected
the SMS with "Invalid or disallowed parameters" while the same number typed
as "+917330671971" on another lead went through.
"""
import pytest

from src.models.crm_models import LeadCreate, LeadUpdate
from src.utils.phone import normalize_phone


@pytest.mark.parametrize("raw, expected", [
    ("+91 7330671971", "+917330671971"),
    ("+917330671971", "+917330671971"),
    ("+1 (512) 555-0101", "+15125550101"),
    ("+1.512.555.0101", "+15125550101"),
    ("  +91 73306 71971  ", "+917330671971"),
    ("7330671971", "7330671971"),  # no country code -> left as typed, never guessed
    ("   ", None),
    (None, None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_lead_create_cleans_every_phone_field():
    lead = LeadCreate(company_name="Karthik", last_name="Harshitha", contact_email="h@example.com",
                      contact_phone="+91 7330671971", mobile_phone="+91-73306-71971",
                      whatsapp_number="+91 (733) 067 1971")
    assert (lead.contact_phone, lead.mobile_phone, lead.whatsapp_number) == \
        ("+917330671971", "+917330671971", "+917330671971")


def test_lead_update_cleans_phone_and_leaves_unset_fields_unset():
    update = LeadUpdate(contact_phone="+91 7330671971")
    assert update.contact_phone == "+917330671971"
    assert update.model_dump(exclude_unset=True) == {"contact_phone": "+917330671971"}
