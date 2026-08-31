# EgoCapture Metadata Generator

Generates structured JSON metadata for egocentric (head-mounted camera) video datasets captured with the **EgoCapture-1** device. It probes each video with `ffprobe`, samples representative frames with `ffmpeg`, optionally uses IMU motion data to pick high-activity keyframes, then calls a Vision Language Model (local Ollama Gemma 3 by default, or Gemini / Claude) to label actions, objects, sub-tasks, handedness, and task difficulty — all written out as per-video `metadata.json` files.

---

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on your PATH
- For the default backend: [Ollama](https://ollama.com) running locally with a Gemma 3 model pulled (`ollama pull gemma3`) — no API key needed
- For cloud backends: a Gemini **or** Anthropic API key

---

## System dependencies

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Ubuntu / Debian:**
```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

Verify:
```bash
ffmpeg -version
ffprobe -version
```

---

## Installation

```bash
git clone https://github.com/yashshah611537/metadata-generator.git
cd metadata-generator
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Backends

### Ollama + Gemma 3 (default — local, no API key)

```bash
ollama serve          # start the local server if it isn't running
ollama pull gemma3    # vision-capable; gemma3:12b / gemma3:27b for better quality
```

Optional overrides (env or `.env`):

```env
OLLAMA_MODEL=gemma3
OLLAMA_HOST=http://localhost:11434
```

### Gemini / Claude (cloud)

Copy the example file and fill in your key(s):

```bash
cp .env.example .env
```

Then edit `.env`:

```env
GEMINI_API_KEY=your-gemini-api-key-here
# OR
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

Export before running:

```bash
export GEMINI_API_KEY="your-gemini-api-key-here"
# or
export ANTHROPIC_API_KEY="your-anthropic-api-key-here"
```

To make them permanent, add the export lines to `~/.zshrc` or `~/.bashrc`.

> **Never** commit your `.env` file — it is listed in `.gitignore`.

---

## Data layout

Your data folder must be arranged like this:

```
/path/to/parent/
├── worker_folder_A/            # immediate subfolder = one worker / operator
│   ├── video_001.mp4
│   ├── video_002.mp4
│   ├── video_001.aac           # optional audio (matched by stem)
│   └── video_001.txt           # optional IMU log (JSON-Lines)
├── worker_folder_B/
│   └── session_2025_02_01/     # nesting is fine — files found recursively
│       ├── clip_01.mp4
│       └── imu.txt
└── ...
```

**Rules:**
- Each immediate subdirectory of `--parent-path` is one worker folder.
- `.mp4`, `.aac`, and `.txt` files are discovered recursively inside each worker folder.
- A `.txt` is treated as IMU data only if its first JSON line contains `t_us` (int), `acc` (list of 3), and `gyro` (list of 3).
- Videos within a worker are natural-sorted (`video_2` before `video_10`).

---

## Running

```bash
python -m egometa --parent-path /path/to/parent
```

The CLI will prompt you interactively for all other settings:

| Prompt | Options / default |
|---|---|
| Company / factory name | free text |
| Company vertical | `garments` · `electronics` · `diamond` · `semiconductor` · `furniture` · `paper` · `household` · `looms` · `granite_stone` · `cooking` · `mahadev` · `toy_factory` |
| Environment preset | `garment_factory` (default) · `electronics_lab` · `diamond_workshop` · `semiconductor_fab` · `furniture_workshop` · `paper_mill` · `home_general` · `home_kitchen` · `loom_floor` · `stone_yard` · `commercial_kitchen` · `mahadev_site` · `toy_factory` · `auto_plant` · `food_plant` |
| City | e.g. `Bengaluru`, `Mumbai`, `Chennai` |
| State/Province | auto-filled from built-in India city map; editable |
| Geohash | auto-derived from city center (7-char base32); editable |
| Operator age bucket | `18-24` · `25-29` (default) · `30-34` … `60+` |
| Operator gender | `Male` · `Female` (default) · `Non-binary` · `Prefer not to say` |
| VLM backend | `ollama` (default, local Gemma 3) · `gemini` · `claude` |
| Frames per VLM call | default `6` |
| Concurrency | default `6` |
| Output directory | default `./metadata_out` |
| Dry run? | `y` / `n` — dry run skips all API calls |
| Registration CSV | optional — per-worker demographic overrides |
| QC CSV | optional — per-worker quality status |
| Limit workers | blank = process all |
| Resume from checkpoint? | `y` / `n` |

### Recommended first run

Always do a dry run first to validate discovery with zero API cost:

```bash
python -m egometa --parent-path /path/to/parent
# answer prompts → choose "y" for Dry run
```

Inspect the generated `metadata.json` files, then rerun and answer `n` to Dry run for the real VLM-labeled output.

---

## Output files

For every worker folder, two identical `metadata.json` files are written:

1. `<output-dir>/<worker_folder>/metadata.json` — central catalog
2. `<worker_folder>/MetaData/metadata.json` — inline, next to the videos

Each individual video also gets a sidecar `<video>.json` next to it.

Additionally:

| File | Description |
|---|---|
| `<output-dir>/checkpoint.sqlite` | Resume state — tracks which workers are DONE / FAILED |
| `<output-dir>/run_report.json` | Summary: workers found / done / failed / frames sent / IMU-missing count |

---

## Optional CSV overrides

### Registration (demographics)

Override age, gender, and handedness per worker:

```csv
worker_folder,age_range,gender,handedness
worker_folder_A,25-29,Female,Right-handed
worker_folder_B,30-34,Male,Left-handed
```

### QC results

Attach quality status per worker:

```csv
worker_folder,quality_status
worker_folder_A,Passed
worker_folder_B,Rework
```

---

## Demographics precedence

`age_range` and `gender` cannot be observed in egocentric video and must be supplied. The order of precedence (highest first):

1. `--registration-csv` row for that worker (`provenance = registration`)
2. Interactive prompt values (`provenance = user_input`) — applied to all workers in the run

Provenance is recorded under `_provenance` in every metadata document.

---

## Resume after a crash

Re-run with the same `--parent-path` and answer `y` at the "Resume?" prompt. Workers already marked `DONE`, `DONE_NO_VLM`, or `DRY_RUN_OK` in the checkpoint are skipped.

---

## Geohash

If the city is in the built-in coordinate map (Bengaluru, Mumbai, Delhi, Chennai, Coimbatore, Hyderabad, Kolkata, Ahmedabad, Surat, Jaipur, Lucknow, Noida, Gurgaon, Tiruppur, Ludhiana, and more), a 7-character base32 geohash is auto-derived and shown to you. You can accept it or enter a more precise geohash for the exact factory site. Unknown cities leave the field as `UNKNOWN - REQUIRED (geo-hash)` until you fill it in.

---

## Supported verticals

| Key | Description |
|---|---|
| `garments` | Garment manufacturing — sewing, stitching, cutting, ironing |
| `electronics` | Electronics assembly — soldering, component placement, wiring |
| `diamond` | Diamond processing — cleaving, bruting, cutting, polishing |
| `semiconductor` | Semiconductor fab — wafer handling, wire-bonding, probing |
| `furniture` | Furniture making — sawing, sanding, drilling, finishing |
| `paper` | Paper processing — roll handling, cutting, stacking, packing |
| `household` | Household chores — cooking, cleaning, laundry, organizing |
| `looms` | Loom weaving — warping, threading, weaving, defect fixing |
| `granite_stone` | Stone processing — cutting, chiseling, grinding, polishing |
| `cooking` | Cooking — chopping, mixing, sautéing, plating |
| `mahadev` | Mahadev project — assembly, sorting, packing, inspection |
| `toy_factory` | Toy manufacturing — molding, fitting, painting, packing |

---

## License

MIT
