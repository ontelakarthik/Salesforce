"""Centralized Country -> State/Province -> Region config.

Single source of truth for the fixed Country/State-Province vocabulary and
the State/Province -> Region derivation used by both Lead (see
services/crm_service.py's create_lead/update_lead/_lead_out) and Account's
billing pair (create_account/update_account/_out). Region is never stored —
like Signal.strength's decayed point contribution (see crm_models.Signal's
docstring), it's derived fresh on every read from Country + State/Province
so it can never drift out of sync with them.

Only USA and Canada are supported today; adding a country later means
adding one entry to STATE_PROVINCES_BY_COUNTRY and one to
_REGION_BY_STATE_PROVINCE, nothing else.
"""
from src.utils.exceptions import DomainError

COUNTRY_USA = "USA"
COUNTRY_CANADA = "Canada"

#: Exactly the 50 US states — District of Columbia is deliberately excluded.
US_STATES: list[str] = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]

#: Exactly the 13 Canadian provinces/territories.
CANADA_PROVINCES: list[str] = [
    "Alberta", "British Columbia", "Manitoba", "New Brunswick",
    "Newfoundland and Labrador", "Nova Scotia", "Ontario",
    "Prince Edward Island", "Quebec", "Saskatchewan",
    "Northwest Territories", "Nunavut", "Yukon",
]

STATE_PROVINCES_BY_COUNTRY: dict[str, list[str]] = {
    COUNTRY_USA: US_STATES,
    COUNTRY_CANADA: CANADA_PROVINCES,
}

#: USA's 4 Census-style regions, keyed by state.
_US_REGION_BY_STATE: dict[str, str] = {
    **{s: "Northeast" for s in (
        "Connecticut", "Maine", "Massachusetts", "New Hampshire",
        "Rhode Island", "Vermont", "New Jersey", "New York", "Pennsylvania",
    )},
    **{s: "Midwest" for s in (
        "Illinois", "Indiana", "Michigan", "Ohio", "Wisconsin", "Iowa",
        "Kansas", "Minnesota", "Missouri", "Nebraska", "North Dakota",
        "South Dakota",
    )},
    **{s: "South" for s in (
        "Delaware", "Florida", "Georgia", "Maryland", "North Carolina",
        "South Carolina", "Virginia", "West Virginia", "Alabama",
        "Kentucky", "Mississippi", "Tennessee", "Arkansas", "Louisiana",
        "Oklahoma", "Texas",
    )},
    **{s: "West" for s in (
        "Arizona", "Colorado", "Idaho", "Montana", "Nevada", "New Mexico",
        "Utah", "Wyoming", "Alaska", "California", "Hawaii", "Oregon",
        "Washington",
    )},
}

#: Canada's 5 regions, keyed by province/territory.
_CANADA_REGION_BY_PROVINCE: dict[str, str] = {
    **{p: "Atlantic" for p in (
        "New Brunswick", "Newfoundland and Labrador", "Nova Scotia",
        "Prince Edward Island",
    )},
    **{p: "Central Canada" for p in ("Ontario", "Quebec")},
    **{p: "Prairies" for p in ("Alberta", "Manitoba", "Saskatchewan")},
    "British Columbia": "West",
    **{p: "North" for p in ("Northwest Territories", "Nunavut", "Yukon")},
}

_REGION_BY_STATE_PROVINCE_BY_COUNTRY: dict[str, dict[str, str]] = {
    COUNTRY_USA: _US_REGION_BY_STATE,
    COUNTRY_CANADA: _CANADA_REGION_BY_PROVINCE,
}


def valid_state_provinces(country: str | None) -> list[str]:
    """The dropdown options for a given country — empty list (not an error)
    for an unsupported/missing country, since callers use this to render an
    empty/disabled State/Province dropdown, not to validate."""
    if country is None:
        return []
    return STATE_PROVINCES_BY_COUNTRY.get(country, [])


def valid_regions(country: str | None) -> list[str]:
    """The Region vocabulary for a given country — every distinct value
    derive_region() can produce for it (see
    _REGION_BY_STATE_PROVINCE_BY_COUNTRY). Used by the Territory master
    object (see admin_service._validate_territory_fields()) to validate its
    own Region field against the same vocabulary Lead/Account's derived
    Region already uses, instead of inventing a second Region concept.
    Empty list (not an error) for an unsupported/missing country, same
    non-raising contract as valid_state_provinces()."""
    if country is None:
        return []
    return sorted(set(_REGION_BY_STATE_PROVINCE_BY_COUNTRY.get(country, {}).values()))


def derive_region(country: str | None, state_province: str | None) -> str | None:
    """Country + State/Province -> Region. None whenever either half is
    missing or the pair doesn't resolve to a known region — never guesses,
    and never assigns one Region to an entire country (see crm_service.py's
    validation, which rejects an invalid pair before this is ever called on
    a write path)."""
    if not country or not state_province:
        return None
    return _REGION_BY_STATE_PROVINCE_BY_COUNTRY.get(country, {}).get(state_province)


def validate_country_state_province(country: str | None, state_province: str | None) -> None:
    """Raises a 422 DomainError for any combination that could produce a
    wrong/silent Region:
    - a State/Province with no Country
    - a Country outside the supported set
    - a State/Province that doesn't belong to the given Country
    Both None (the default, unset case) is valid — see edge case "Missing
    Country/State: application must not crash; Region stays null"."""
    if state_province and not country:
        raise DomainError(
            "STATE_PROVINCE_REQUIRES_COUNTRY",
            "state_province requires country to be set.", 422)
    if country is None:
        return
    if country not in STATE_PROVINCES_BY_COUNTRY:
        raise DomainError(
            "INVALID_COUNTRY",
            f"'{country}' is not a supported country. Supported: "
            f"{', '.join(STATE_PROVINCES_BY_COUNTRY)}.", 422)
    if state_province and state_province not in STATE_PROVINCES_BY_COUNTRY[country]:
        raise DomainError(
            "INVALID_STATE_PROVINCE",
            f"'{state_province}' is not a valid state/province for {country}.", 422)
