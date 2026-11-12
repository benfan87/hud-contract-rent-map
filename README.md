# HUD Contract Rent Map

Search HUD-assisted multifamily properties by name, address, HUD property ID or contract number, or drop a pin.
Pick a radius to see nearby properties on a map and in a linked table, filter by contract type, program, status,
renewal option, contract start year and length, bedrooms and rent basis, and export the results to CSV.

**Data:** HUD Multifamily Assistance & Section 8 Contracts, contract renewal, contract rent / utility allowance and
property files (HUD publication of 2026-10-06, downloaded 2026-10-27), joined on HUD property ID and contract number.
Coordinates come from HUD's *Multifamily Properties - Assisted* GIS layer; properties it does not locate are placed at
their Census ZIP (ZCTA) centroid and flagged approximate.

**Rents & UAs:** per-bedroom contract rents, utility allowances and FMRs come from HUD's *Contracts with Rent amt and
Utility Allowance amt* file (https://www.hud.gov/hud-partners/multifamily-preservation). Refresh them with
`python tools/merge_rent_ua.py <contractsrentutilityamt.xlsx> --asof YYYY-MM-DD` (needs `openpyxl`; downloads the file
if the path does not exist). It rewrites `assets/hud_data.js` in place, replacing the rent lines of every contract in
HUD's file and keeping verified-document lines.

**Rents:** *Reported* amounts are HUD contract rents and utility allowances. *Estimates* are gross rents only
(assistance-file bedroom FMR x HUD contract rent-to-FMR %), applied to every bedroom size; no contract rent is
estimated when the utility allowance is unknown. A static snapshot, for screening only: HUD contract rents and FMRs
are not market rents or rent comparability study conclusions. Verify before relying on any figure.

**Financing, LIHTC and 2027 QCT/DDA** (run from the repo root, in this order, after `merge_rent_ua.py`):

1. `python tools/merge_fha.py <folder> --loans-asof YYYY-MM-DD`: FHA loans (Section of the Act, endorsement, maturity, rate,
   balance, TC/TE flags) from HUD's active insured-mortgage file, linked through the active-portfolio FHA tab; ownership dates.
2. `python tools/fetch_lihtc_hud.py hud_lihtc.json`: HUD LIHTC database (HUD eGIS layer, all records).
3. `python tools/parse_az_lihtc.py LIHTCandBond-Projects.xlsx az_lihtc.json --published YYYY-MM`: Arizona ADOH award list
   (download it in a normal browser; the site has a bot check). Add other states the same way.
4. `python tools/match_lihtc.py hud_lihtc.json az_lihtc.json matches.json`, then `python tools/merge_lihtc.py matches.json`.
5. `python tools/build_qct_dda.py 2027` (writes `assets/qct_dda_2027.js` and a property flag file), then
   `python tools/merge_zones.py property_qct_dda_2027.json --year 2027`.
6. `python tools/merge_owners.py <folder>`: owner entity, management agent and their HUD contacts from the MF Assistance &
   Section 8 property file, plus owner groups (likely sponsor: shared organization email domain, else mailing address).

LIHTC records have no HUD property ID, so they are matched by address, location and name, with a confidence label.
Treat the target screen as a shortlist to verify, not a conclusion.
