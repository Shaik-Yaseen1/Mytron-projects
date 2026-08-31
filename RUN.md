#RUN — EgoCapture Metadata Generator

Only one CLI flag — everything else is asked interactively.

```bash
python -m egometa --parent-path /path/to/parent
```

You'll then be prompted for:

| Prompt | Notes / default |
|---|---|
| Company / factory name | free text |
| Company vertical | `garment` (default) / `auto_components` / `electronics` / `food_processing` / `household` |
| Environment preset | `garment_factory` (default) / `auto_plant` / `electronics_lab` / `food_plant` / `home_kitchen` / `home_general` |
| City | Bengaluru, Mumbai, etc. |
| State/Province | Auto-filled from an India city map when known; editable |
| Geohash | **Auto-derived** from city coordinates (7-char base32). Editable, or press Enter to accept |
| Operator age bucket | 18-24 / 25-29 (default) / 30-34 / 35-39 / 40-44 / 45-49 / 50-54 / 55-59 / 60+ |
| Operator gender | Male / Female (default) / Non-binary / Prefer not to say |
| VLM backend | `ollama` (default, local Gemma 3) · `gemini` · `claude` |
| Frames per worker | default 6 |
| Concurrency | default 6 |
| Output directory | default `./metadata_out` |
| Dry run? | `y` / `n` — dry run makes no API calls |
| Registration CSV | optional per-worker demographic overrides |
| QC CSV | optional per-worker quality status |
| Limit | blank = all workers |
| Resume | `y` / `n` (uses SQLite checkpoint) |

## Geohash generation

If the entered city is present in the built-in coordinate map
(Bengaluru, Mumbai, Delhi, Chennai, Coimbatore, Hyderabad, Kolkata, Ahmedabad,
Surat, Jaipur, Lucknow, Noida, Gurgaon, Tiruppur, Ludhiana, …), a standard
7-character base32 geohash is computed from the city center and shown to you.
You can accept it or override with a more precise geohash for the factory site.
If the city is unknown, the field stays `UNKNOWN - REQUIRED (geo-hash)` until
you enter one.

## Where metadata.json is written

For every worker folder, `metadata.json` is written **twice**:

1. `<output-dir>/<worker_folder>/metadata.json` — the central catalog
2. `<worker_folder>/MetaData/metadata.json` — inline next to the videos

Both files are identical. The inline copy makes the worker folder self-describing
so it can be shipped independently.

Also produced:
- `<output-dir>/checkpoint.sqlite` — resume state
- `<output-dir>/run_report.json` — summary (found / done / failed / frames sent / IMU-missing count)

## Recommended first run

Always start with a dry run to validate discovery — no API cost:

```bash
python -m egometa --parent-path /path/to/parent
# ...answer prompts, choose "y" for Dry run
```

Inspect the preliminary `metadata.json` files, then rerun and answer "n" to Dry
run for the real (VLM-labeled) run.

## Demographics rule

`age_range` and `gender` cannot be observed in egocentric video, so they must
be supplied. Order of precedence (highest first):

1. `--registration-csv` row for that worker (provenance = `registration`)
2. Interactive prompt values (provenance = `user_input`) — apply to all workers in the run

Provenance is recorded on every metadata document under `_provenance`.

## Resume after a crash

Rerun with the same `--parent-path`, and answer **y** at the "Resume?" prompt.
Workers with `DONE` / `DONE_NO_VLM` / `DRY_RUN_OK` in the checkpoint are skipped.
