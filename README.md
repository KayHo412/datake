# Datake

Automated data processing tool for CSV and Excel files.

This project is being built in phases. **Phase 5** is in place: read, validate,
clean, merge, and automatically process incoming CSV and Excel (`.xlsx`) files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
datake read data/input/sample_customers.csv
datake read data/input/sample_customers.xlsx
datake validate data/input/sample_customers_dirty.csv
datake clean data/input/sample_customers_dirty.csv
datake merge
datake watch --once
datake watch
```

- `read` — load a CSV or `.xlsx` file and show rows (does not change it)
- `validate` — list quality problems (does not change it)
- `clean` — write a cleaned copy to `data/processed/` (original stays in `data/input/`)
- `merge` — clean files in `data/input/` and combine those with the same columns
- `watch --once` — process the current input batch and exit
- `watch` — poll `data/input/` continuously for new files

## Automated processing

`watch` makes file processing idempotent and auditable:

- Successfully processed inputs move to `data/archive/`.
- Files that cannot be read or processed move to `data/quarantine/`.
- Rejected rows are preserved in `data/quarantine/*_rejected.csv` with a
  `rejection_reason` column.
- Each run creates a JSON report in `data/reports/`.
- `data/datake.db` stores SHA-256 file hashes and run outcomes, so the same
  file content is not processed twice.

The default polling interval is five seconds and can be changed in
`config/settings.json`:

```json
{
  "automation": {
    "watch_interval": 5
  }
}
```

For a one-off batch, use `datake watch --once`. For a long-running worker,
use `datake watch` and stop it with `Ctrl-C`. The optional `--interval` flag
overrides the configured interval for that run.

Cleaning rules live in `config/settings.json` under `"cleaning"`.

The default supported input extensions are `.csv` and `.xlsx`. Excel files are
read from their first worksheet and cleaned outputs are written as CSV files.

## Tests

```bash
pytest
```
