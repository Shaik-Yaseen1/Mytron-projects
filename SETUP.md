# SETUP — EgoCapture Metadata Generator

Runs on macOS (Intel/Apple Silicon) and Linux. Python 3.10+ required.

## 1. System dependencies

You need `ffmpeg` and `ffprobe` on your PATH.

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

Verify:
```bash
ffmpeg -version
ffprobe -version
```

## 2. Python environment

```bash
cd metadata_generator
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Backend setup (choose one)

**Ollama + Gemma 3 (default, local, no API key):**
```bash
# install ollama from https://ollama.com, then:
ollama serve            # runs the local server (or it may already be running)
ollama pull gemma3      # vision-capable; gemma3:12b / gemma3:27b for better quality
```
Optional overrides: `OLLAMA_MODEL` (default `gemma3`), `OLLAMA_HOST` (default `http://localhost:11434`).

The cloud backends below read keys from environment variables. Never pass them on the command line.

**Gemini:**
```bash
export GEMINI_API_KEY="your-gemini-key"
```

**Anthropic Claude:**
```bash
export ANTHROPIC_API_KEY="your-anthropic-key"
```

Add to `~/.zshrc` or `~/.bashrc` to make persistent.

## 4. Data layout expected

```
/path/to/parent/
├── worker_folder_A/            # arbitrary names — folder name is the worker key
│   ├── video_1.mp4             # anywhere in the tree
│   ├── video_2.mp4
│   ├── audio_1.aac             # optional
│   └── imu_log.txt             # JSON-Lines with t_us/acc/gyro
├── worker_folder_B/
│   └── session_2025_02_01/     # nesting is fine — files are found recursively
│       ├── video_1.mp4
│       └── imu.txt
└── ...
```

Rules:
- Subdirectories of `--parent-path` are worker folders.
- `.mp4`, `.aac`, `.txt` are discovered recursively.
- A `.txt` is treated as IMU only if its first JSON line contains `t_us` (int), `acc` (list[3]), and `gyro` (list[3]). Anything else is ignored.
- Video chunks are natural-sorted (`video_2` before `video_10`).

## 5. Optional CSVs

**Registration (demographics)** — columns:
```csv
worker_folder,age_range,gender,handedness
worker_folder_A,25-29,Female,Right-handed
```

**QC results** — columns:
```csv
worker_folder,quality_status
worker_folder_A,Passed
worker_folder_B,Rework
```

You are ready. See `RUN.md`.
