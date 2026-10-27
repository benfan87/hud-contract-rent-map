# HUD Contract Rent Map

Search HUD-assisted multifamily properties by name, address, HUD property ID or contract number, or drop a pin.
Pick a radius to see nearby properties on a map and in a linked table, filter by contract type, program, status,
renewal option, contract start year and length, bedrooms and rent basis, and export the results to CSV.

**Data:** HUD Multifamily Assistance & Section 8 Contracts, contract renewal, contract rent / utility allowance and
property files (HUD publication of 2026-10-06, downloaded 2026-10-27), joined on HUD property ID and contract number.
Coordinates come from HUD's *Multifamily Properties - Assisted* GIS layer; properties it does not locate are placed at
their Census ZIP (ZCTA) centroid and flagged approximate.

**Rents:** *Reported* amounts are HUD contract rents and utility allowances. *Estimates* are gross rents only
(assistance-file bedroom FMR x HUD contract rent-to-FMR %), applied to every bedroom size; no contract rent is
estimated when the utility allowance is unknown. A static snapshot, for screening only: HUD contract rents and FMRs
are not market rents or rent comparability study conclusions. Verify before relying on any figure.
