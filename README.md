# Datake

Automated data processing tool for CSV and Excel files.

This project is being built in phases. **Phase 1** is in place: project layout and CSV reading.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Phase 1 usage

```bash
datake read data/input/sample_customers.csv
```

Configuration lives in `config/settings.json`. Paths in that file are relative to the project root.

## Tests

```bash
pytest
```
