#!/usr/bin/env bash
#
# upload_videos_to_gcs.sh
#
# Upload video files from a local directory to a Google Cloud Storage bucket.
#
# Usage:
#   ./upload_videos_to_gcs.sh -s /path/to/local/videos -b my-bucket-name [options]
#
# Options:
#   -s, --source DIR        Local directory containing videos (required)
#   -b, --bucket NAME       Destination GCS bucket name, without gs:// (required)
#   -p, --prefix PATH       Destination path prefix inside the bucket (default: "")
#   -e, --extensions LIST   Comma-separated list of video extensions to match
#                           (default: mp4,mov,avi,mkv,webm,m4v,flv,wmv)
#   -j, --project ID        GCP project ID to use (default: current gcloud config)
#   -n, --dry-run           Show what would be uploaded without uploading
#   -d, --delete-source     Delete local file after a verified successful upload
#   -h, --help              Show this help message
#
# Requires: gcloud CLI, authenticated (`gcloud auth login`), and permission
#           to write to the target bucket.

set -euo pipefail

# ---- defaults ----
SRC_DIR=""
BUCKET=""
PREFIX=""
EXTENSIONS="mp4,mov,avi,mkv,webm,m4v,flv,wmv"
PROJECT=""
DRY_RUN=false
DELETE_SOURCE=false
LOG_FILE="gcs_upload_$(date +%Y%m%d_%H%M%S).log"

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---- parse args ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--source) SRC_DIR="$2"; shift 2 ;;
    -b|--bucket) BUCKET="$2"; shift 2 ;;
    -p|--prefix) PREFIX="$2"; shift 2 ;;
    -e|--extensions) EXTENSIONS="$2"; shift 2 ;;
    -j|--project) PROJECT="$2"; shift 2 ;;
    -n|--dry-run) DRY_RUN=true; shift ;;
    -d|--delete-source) DELETE_SOURCE=true; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

# ---- validate inputs ----
if [[ -z "$SRC_DIR" || -z "$BUCKET" ]]; then
  echo "Error: --source and --bucket are required." >&2
  usage 1
fi

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Error: source directory '$SRC_DIR' does not exist." >&2
  exit 1
fi

if ! command -v gcloud &>/dev/null; then
  echo "Error: gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install" >&2
  exit 1
fi

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo "Error: no active gcloud auth session. Run: gcloud auth login" >&2
  exit 1
fi

PROJECT_FLAG=()
if [[ -n "$PROJECT" ]]; then
  PROJECT_FLAG=(--project="$PROJECT")
fi

# Confirm bucket exists and is reachable
if ! gcloud storage buckets describe "gs://${BUCKET}" "${PROJECT_FLAG[@]+"${PROJECT_FLAG[@]}"}" &>/dev/null; then
  echo "Error: bucket 'gs://${BUCKET}' not found or not accessible with current credentials." >&2
  exit 1
fi

# strip leading/trailing slashes from prefix
PREFIX="${PREFIX#/}"
PREFIX="${PREFIX%/}"
DEST_BASE="gs://${BUCKET}"
[[ -n "$PREFIX" ]] && DEST_BASE="${DEST_BASE}/${PREFIX}"

# ---- build find expression for extensions ----
IFS=',' read -ra EXT_ARR <<< "$EXTENSIONS"
FIND_EXPR=()
for ext in "${EXT_ARR[@]}"; do
  [[ ${#FIND_EXPR[@]} -gt 0 ]] && FIND_EXPR+=(-o)
  FIND_EXPR+=(-iname "*.${ext}")
done

FILES=()
while IFS= read -r -d '' f; do
  FILES+=("$f")
done < <(find "$SRC_DIR" -type f \( "${FIND_EXPR[@]}" \) -print0)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No files matching extensions [${EXTENSIONS}] found in '${SRC_DIR}'."
  exit 0
fi

echo "Found ${#FILES[@]} video file(s) in '${SRC_DIR}'."
echo "Destination: ${DEST_BASE}/"
echo "Dry run: ${DRY_RUN}"
echo "Log file: ${LOG_FILE}"
echo "---"

{
  echo "Upload started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Source: ${SRC_DIR}"
  echo "Destination: ${DEST_BASE}/"
} >> "$LOG_FILE"

SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

for FILE in "${FILES[@]}"; do
  REL_PATH="${FILE#"$SRC_DIR"/}"
  FILENAME="${FILE##*/}"
  EXT_LC=$(printf '%s' "${FILENAME##*.}" | tr '[:upper:]' '[:lower:]')

  REL_DIR="${REL_PATH%/*}"
  [[ "$REL_DIR" == "$REL_PATH" ]] && REL_DIR=""

  # Route by file type into Videos/ or IMU/ subfolders, regardless of local layout
  case "$EXT_LC" in
    mp4|mov|avi|mkv|webm|m4v|flv|wmv) TYPE_DIR="Videos" ;;
    txt|aac) TYPE_DIR="IMU" ;;
    *) TYPE_DIR="" ;;
  esac

  if [[ -n "$TYPE_DIR" ]]; then
    DEST_REL="${REL_DIR:+$REL_DIR/}${TYPE_DIR}/${FILENAME}"
  else
    DEST_REL="$REL_PATH"
  fi

  DEST="${DEST_BASE}/${DEST_REL}"
  LOCAL_SIZE=$(stat -f%z "$FILE" 2>/dev/null || stat -c%s "$FILE")

  # Skip if an object of the same size already exists at destination (basic incremental check)
  REMOTE_SIZE=$(gcloud storage objects describe "$DEST" "${PROJECT_FLAG[@]+"${PROJECT_FLAG[@]}"}" \
                  --format="value(size)" 2>/dev/null || echo "")
  if [[ -n "$REMOTE_SIZE" && "$REMOTE_SIZE" == "$LOCAL_SIZE" ]]; then
    echo "SKIP  (already exists, same size): $DEST_REL"
    echo "SKIP $FILE -> $DEST" >> "$LOG_FILE"
    ((SKIP_COUNT++))
    continue
  fi

  if $DRY_RUN; then
    echo "DRY-RUN would upload: $FILE -> $DEST"
    continue
  fi

  echo "Uploading: $DEST_REL ..."
  if gcloud storage cp "$FILE" "$DEST" "${PROJECT_FLAG[@]+"${PROJECT_FLAG[@]}"}" --no-user-output-enabled; then
    echo "OK    $FILE -> $DEST" >> "$LOG_FILE"
    ((SUCCESS_COUNT++))

    if $DELETE_SOURCE; then
      # Re-verify remote size before deleting local copy
      VERIFY_SIZE=$(gcloud storage objects describe "$DEST" "${PROJECT_FLAG[@]+"${PROJECT_FLAG[@]}"}" \
                      --format="value(size)" 2>/dev/null || echo "")
      if [[ "$VERIFY_SIZE" == "$LOCAL_SIZE" ]]; then
        rm -- "$FILE"
        echo "DELETED local copy of $FILE" >> "$LOG_FILE"
      else
        echo "WARNING: size mismatch after upload, keeping local file: $FILE" >&2
        echo "WARN size-mismatch, kept local $FILE" >> "$LOG_FILE"
      fi
    fi
  else
    echo "FAILED to upload: $FILE" >&2
    echo "FAIL  $FILE -> $DEST" >> "$LOG_FILE"
    ((FAIL_COUNT++))
  fi
done

echo "---"
echo "Done. Success: ${SUCCESS_COUNT}, Skipped: ${SKIP_COUNT}, Failed: ${FAIL_COUNT}"
echo "Summary: success=${SUCCESS_COUNT} skipped=${SKIP_COUNT} failed=${FAIL_COUNT}" >> "$LOG_FILE"

[[ $FAIL_COUNT -eq 0 ]] || exit 1
