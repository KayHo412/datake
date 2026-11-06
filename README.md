# Datake

Automated data processing tool for CSV and Excel files.

This project is being built in phases. **Phase 3** is in place: read, validate, clean, and merge CSV files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
datake read data/input/sample_customers.csv
datake validate data/input/sample_customers_dirty.csv
datake clean data/input/sample_customers_dirty.csv
datake merge
```

- `read` — load a file and show rows (does not change it)
- `validate` — list quality problems (does not change it)
- `clean` — write a cleaned copy to `data/processed/` (original stays in `data/input/`)
- `merge` — clean files in `data/input/` and combine those with the same columns

Cleaning rules live in `config/settings.json` under `"cleaning"`.

## Tests

```bash
pytest
```
