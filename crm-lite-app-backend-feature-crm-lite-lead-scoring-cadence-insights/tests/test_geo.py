"""Country -> State/Province -> Region config (src/utils/geo.py). Pure
functions, no DB needed — unlike the rest of this suite (see CLAUDE.md)."""
import pytest

from src.utils import geo
from src.utils.exceptions import DomainError


class TestStateProvinceLists:
    def test_usa_has_exactly_50_states(self):
        assert len(geo.US_STATES) == 50

    def test_usa_excludes_district_of_columbia(self):
        assert "District of Columbia" not in geo.US_STATES
        assert "Washington DC" not in geo.US_STATES

    def test_canada_has_exactly_13_provinces_territories(self):
        assert len(geo.CANADA_PROVINCES) == 13

    def test_valid_state_provinces_empty_for_unknown_or_missing_country(self):
        assert geo.valid_state_provinces(None) == []
        assert geo.valid_state_provinces("") == []
        assert geo.valid_state_provinces("Mexico") == []


class TestRegionDerivation:
    @pytest.mark.parametrize("state,expected", [
        ("California", "West"),
        ("Texas", "South"),
        ("New York", "Northeast"),
        ("Illinois", "Midwest"),
    ])
    def test_usa_region_examples(self, state, expected):
        assert geo.derive_region("USA", state) == expected

    @pytest.mark.parametrize("province,expected", [
        ("Alberta", "Prairies"),
        ("Manitoba", "Prairies"),
        ("Saskatchewan", "Prairies"),
        ("Ontario", "Central Canada"),
        ("Quebec", "Central Canada"),
        ("British Columbia", "West"),
        ("New Brunswick", "Atlantic"),
        ("Nova Scotia", "Atlantic"),
        ("Prince Edward Island", "Atlantic"),
        ("Newfoundland and Labrador", "Atlantic"),
        ("Yukon", "North"),
        ("Northwest Territories", "North"),
        ("Nunavut", "North"),
    ])
    def test_canada_region_examples(self, province, expected):
        assert geo.derive_region("Canada", province) == expected

    def test_every_us_state_maps_to_a_region(self):
        for state in geo.US_STATES:
            assert geo.derive_region("USA", state) is not None, state

    def test_every_canada_province_maps_to_a_region(self):
        for province in geo.CANADA_PROVINCES:
            assert geo.derive_region("Canada", province) is not None, province

    def test_missing_country_or_state_gives_none_not_a_crash(self):
        assert geo.derive_region(None, None) is None
        assert geo.derive_region("USA", None) is None
        assert geo.derive_region(None, "California") is None

    def test_mismatched_country_state_gives_none_not_a_wrong_region(self):
        # A Canadian province looked up under USA (or vice versa) must never
        # resolve to some other region by accident.
        assert geo.derive_region("USA", "Ontario") is None
        assert geo.derive_region("Canada", "Texas") is None


class TestValidation:
    def test_both_none_is_valid(self):
        geo.validate_country_state_province(None, None)  # must not raise

    def test_valid_pairs_do_not_raise(self):
        geo.validate_country_state_province("USA", "California")
        geo.validate_country_state_province("Canada", "Ontario")
        geo.validate_country_state_province("USA", None)

    def test_state_without_country_is_rejected(self):
        with pytest.raises(DomainError) as exc:
            geo.validate_country_state_province(None, "California")
        assert exc.value.code == "STATE_PROVINCE_REQUIRES_COUNTRY"

    def test_unsupported_country_is_rejected(self):
        with pytest.raises(DomainError) as exc:
            geo.validate_country_state_province("Mexico", None)
        assert exc.value.code == "INVALID_COUNTRY"

    def test_state_not_belonging_to_country_is_rejected(self):
        with pytest.raises(DomainError) as exc:
            geo.validate_country_state_province("USA", "Ontario")
        assert exc.value.code == "INVALID_STATE_PROVINCE"

        with pytest.raises(DomainError) as exc:
            geo.validate_country_state_province("Canada", "Texas")
        assert exc.value.code == "INVALID_STATE_PROVINCE"
