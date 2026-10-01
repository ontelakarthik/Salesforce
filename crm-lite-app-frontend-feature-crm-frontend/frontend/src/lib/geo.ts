/**
 * Centralized Country -> State/Province config — single source of truth for
 * the Country/State-Province dropdowns on Account and Lead forms. Mirrors
 * src/utils/geo.py on the backend, which is also where Region is actually
 * derived (see LeadOut.region) — this file only needs the dropdown option
 * lists, not the Region mapping, since Region is never entered here.
 *
 * Adding a country later means adding one entry to STATE_PROVINCES_BY_COUNTRY
 * (and its backend counterpart), nothing else.
 */
export const COUNTRY_USA = "USA";
export const COUNTRY_CANADA = "Canada";

export const COUNTRIES = [COUNTRY_USA, COUNTRY_CANADA] as const;

/** Exactly the 50 US states — District of Columbia is deliberately excluded. */
export const US_STATES: string[] = [
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
];

/** Exactly the 13 Canadian provinces/territories. */
export const CANADA_PROVINCES: string[] = [
  "Alberta", "British Columbia", "Manitoba", "New Brunswick",
  "Newfoundland and Labrador", "Nova Scotia", "Ontario",
  "Prince Edward Island", "Quebec", "Saskatchewan",
  "Northwest Territories", "Nunavut", "Yukon",
];

export const STATE_PROVINCES_BY_COUNTRY: Record<string, string[]> = {
  [COUNTRY_USA]: US_STATES,
  [COUNTRY_CANADA]: CANADA_PROVINCES,
};

/** Dropdown options for a given country — [] (not an error) for an empty/
 * unsupported country, so callers can render an empty/disabled
 * State/Province dropdown directly off this. */
export function getStateProvinceOptions(country: string | null | undefined): string[] {
  if (!country) return [];
  return STATE_PROVINCES_BY_COUNTRY[country] ?? [];
}

/** Label for the State/Province dropdown's placeholder option — matches the
 * per-country wording called for in the spec ("Select State" vs "Select
 * Province/Territory"). */
export function stateProvinceLabel(country: string | null | undefined): string {
  if (country === COUNTRY_CANADA) return "Province/Territory";
  return "State";
}

/**
 * Region vocabulary per country — mirrors the Region values backend
 * src/utils/geo.py's derive_region() can produce (its
 * _REGION_BY_STATE_PROVINCE_BY_COUNTRY, deduplicated). Used only by the
 * Territory master object's Region dropdown (Lookups.tsx) — Lead/Account
 * never enter a Region directly, theirs is always server-derived.
 */
export const REGIONS_BY_COUNTRY: Record<string, string[]> = {
  [COUNTRY_USA]: ["Midwest", "Northeast", "South", "West"],
  [COUNTRY_CANADA]: ["Atlantic", "Central Canada", "North", "Prairies", "West"],
};

/** Dropdown options for a given country's Region field — [] (not an error)
 * for an empty/unsupported country, same contract as
 * getStateProvinceOptions(). */
export function getRegionOptions(country: string | null | undefined): string[] {
  if (!country) return [];
  return REGIONS_BY_COUNTRY[country] ?? [];
}
