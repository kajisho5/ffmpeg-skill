# Defect ledger

One file per fixed defect (#632, #678): `<date>-<issue or slug>.json`, for example
`2026-11-26-731.json`, holding one JSON object:

```json
{"date": "2026-11-26", "issue": 731, "class": "claim", "what": "...", "escaped": "...", "mechanism": "..."}
```

`class` is one of the twenty review questions, an FFmpeg version difference, or `new`
(`tests/test_contract.py`, `DEFECT_CLASSES`); `mechanism: null` needs `why_none`; a fix over the
size limit gives `size_reason`. A fix adds its own file, so two open fixes never conflict here.

`../defect-ledger.jsonl` holds the entries written before this directory existed. It is read as
it is and not appended to. `.github/scripts/defect_ledger.py` reads both.
