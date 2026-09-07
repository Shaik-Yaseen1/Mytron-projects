# Mytron data-pipeline scripts (All-Scripts)

One menu-driven launcher that bundles every standalone script from the other
branches. Run it and pick an operation:

```bash
python3 run.py
```

```
============================================================
  Mytron data pipeline — pick an operation
============================================================
  1. Format SD card(s)            — erase & format external removable cards
  2. Convert .build -> .mp4       — fix dashcam/DVR file extensions
  3. Count .mp4 files & size      — tally videos in a folder
  4. Unzip all .zip files         — safe bulk extract
  5. Upload videos to GCS         — push a folder to a Cloud Storage bucket
  6. Generate video metadata      — VLM-labeled metadata.json (egometa)
  0. Exit
```

Each option asks only for the inputs it needs (folder paths, bucket name, y/n
flags) and then runs the underlying tool. Nothing is hidden — the exact command
is printed before it runs.

## Layout

| Path | Source branch | What it does |
|---|---|---|
| `run.py` | — | The unified menu launcher |
| `scripts/format_sd.py` | `Data-Format-App` | Format external removable SD cards (macOS), repeat cycle |
| `scripts/build_to_mp4.py` | `build-to-mp4` | Rename/copy `.build` files to `.mp4` |
| `scripts/count_mp4.py` | `count_mp4` | Count `.mp4` files and total size |
| `scripts/unzip_all.py` | `unzip_files` | Bulk-extract `.zip` files safely |
| `scripts/upload_videos_to_gcs.sh` | `GCP-Shell-Script` | Upload videos to a GCS bucket |
| `egometa/` | `metadata-generator` | VLM metadata generator (`python -m egometa`) |

You can still call any script directly, e.g. `python3 scripts/count_mp4.py -r ~/Videos`.

## Requirements

- **Python 3.10+**
- Option 1 (Format SD): macOS only (`diskutil`). May need `sudo`.
- Option 2–4: standard library only.
- Option 5 (GCS upload): [`gcloud` CLI](https://cloud.google.com/sdk/docs/install),
  authenticated with `gcloud auth login`.
- Option 6 (metadata): `ffmpeg` + `ffprobe` on PATH, a Gemini **or** Anthropic
  API key, and the Python deps:

  ```bash
  pip install -r requirements.txt
  cp .env.example .env   # then fill in GEMINI_API_KEY or ANTHROPIC_API_KEY
  ```

  See `egometa` prompts / `RUN.md` history on the `metadata-generator` branch
  for the full list of interactive options.

## Safety notes

- **Option 1 formats disks — every listed SD card is erased.** It only lists
  external *removable* media (never internal drives), and asks for confirmation
  before the live table opens.
- **Option 5** with "delete local file after upload" removes source files once
  the remote size is verified. Start with the default dry run.
