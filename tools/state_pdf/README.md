# State LIHTC PDF extractions

Some state housing agencies publish LIHTC award lists only as PDFs. Each `<st>.py` here downloads (plain HTTP, no
browser spoofing) and parses that state's PDFs into `hud_src/lihtc/states/extracted/<st>.csv` with these columns:

`PROJECT, PROJ_ADD, PROJ_CTY, PROJ_ZIP, YR_ALLOC, CREDIT, N_UNITS, LI_UNITS, COMPANY, ALLOCAMT, STATE_ID, SRC_LABEL, SRC_URL`

- CREDIT is `9%` or `4% (bond)` (blank if the list doesn't say). YR_ALLOC is the award / reservation year (4 digits).
- One row per project per award (a project awarded in two years appears twice).
- SRC_LABEL names the list, e.g. "Utah Housing Corp. 2024 federal & state credit awards"; SRC_URL is the PDF URL.

`tools/parse_state_lihtc.py` reads the CSVs through `tools/state_lihtc_sources.json` entries with `"csv_std": true`.
Usage: `python tools/state_pdf/<st>.py --out ../hud_src/lihtc/states/extracted` (run from the repo root).
