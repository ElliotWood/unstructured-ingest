#!/usr/bin/env bash

set -e

SRC_PATH=$(dirname "$(realpath "$0")")
SCRIPT_DIR=$(dirname "$SRC_PATH")
cd "$SCRIPT_DIR"/.. || exit 1
OUTPUT_FOLDER_NAME=Sharepoint
OUTPUT_ROOT=${OUTPUT_ROOT:-$SCRIPT_DIR}
OUTPUT_DIR=$OUTPUT_ROOT/structured-output/$OUTPUT_FOLDER_NAME
WORK_DIR=$OUTPUT_ROOT/workdir/$OUTPUT_FOLDER_NAME
DOWNLOAD_DIR=$SCRIPT_DIR/download/$OUTPUT_FOLDER_NAME
max_processes=${MAX_PROCESSES:=$(python3 -c "import os; print(os.cpu_count())")}
CI=${CI:-"false"}

# shellcheck disable=SC1091
source "$SCRIPT_DIR"/cleanup.sh
# shellcheck disable=SC2317
function cleanup() {
  cleanup_dir "$OUTPUT_DIR"
  cleanup_dir "$WORK_DIR"
  if [ "$CI" == "true" ]; then
    cleanup_dir "$DOWNLOAD_DIR"
  fi
}
trap cleanup EXIT

if [ -z "$SHAREPOINT_CLIENT_ID" ] || [ -z "$SHAREPOINT_CRED" ]; then
  echo "Skipping Sharepoint ingest test because the SHAREPOINT_CLIENT_ID or SHAREPOINT_CRED env var is not set."
  exit 8
fi

# excluding metadata.last_modified since this will always update as date processed because the Sharepoint connector creates documents on the fly
RUN_SCRIPT=${RUN_SCRIPT:-./unstructured_ingest/main.py}
PYTHONPATH=${PYTHONPATH:-.} "$RUN_SCRIPT" \
  sharepoint \
  --api-key "$UNS_PAID_API_KEY" \
  --partition-by-api \
  --partition-endpoint "https://api.unstructuredapp.io" \
  --download-dir "$DOWNLOAD_DIR" \
  --metadata-exclude file_directory,metadata.data_source.date_processed,metadata.last_modified,metadata.detection_class_prob,metadata.parent_id,metadata.category_depth \
  --num-processes "$max_processes" \
  --strategy hi_res \
  --preserve-downloads \
  --reprocess \
  --output-dir "$OUTPUT_DIR" \
  --verbose \
  --client-cred "$SHAREPOINT_CRED" \
  --client-id "$SHAREPOINT_CLIENT_ID" \
  --site "$SHAREPOINT_SITE" \
  --recursive \
  --work-dir "$WORK_DIR"

"$SCRIPT_DIR"/check-diff-expected-output.py --output-folder-name $OUTPUT_FOLDER_NAME
