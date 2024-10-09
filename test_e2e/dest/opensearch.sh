#!/usr/bin/env bash

set -e

DEST_PATH=$(dirname "$(realpath "$0")")
SCRIPT_DIR=$(dirname "$DEST_PATH")
cd "$SCRIPT_DIR"/.. || exit 1
OUTPUT_FOLDER_NAME=opensearch-dest
OUTPUT_ROOT=${OUTPUT_ROOT:-$SCRIPT_DIR}
OUTPUT_DIR=$OUTPUT_ROOT/structured-output/$OUTPUT_FOLDER_NAME
WORK_DIR=$OUTPUT_ROOT/workdir/$OUTPUT_FOLDER_NAME
CI=${CI:-"false"}
max_processes=${MAX_PROCESSES:=$(python3 -c "import os; print(os.cpu_count())")}

# shellcheck disable=SC1091
source "$SCRIPT_DIR"/cleanup.sh
function cleanup {
	# Index cleanup
	echo "Stopping OpenSearch Docker container"
	docker compose -f "$SCRIPT_DIR"/env_setup/opensearch/common/docker-compose.yaml down --remove-orphans -v

	# Local file cleanup
	cleanup_dir "$WORK_DIR"
	cleanup_dir "$OUTPUT_DIR"
	if [ "$CI" == "true" ]; then
		cleanup_dir "$DOWNLOAD_DIR"
	fi
}

trap cleanup EXIT

echo "Creating opensearch instance"
# shellcheck source=/dev/null
"$SCRIPT_DIR"/env_setup/opensearch/destination_connector/create-opensearch-instance.sh
wait

PYTHONPATH=. ./unstructured_ingest/main.py \
local \
--num-processes "$max_processes" \
--output-dir "$OUTPUT_DIR" \
--strategy fast \
--verbose \
--reprocess \
--input-path example-docs/pdf/fake-memo.pdf \
--work-dir "$WORK_DIR" \
--embedding-provider "huggingface" \
opensearch \
--hosts http://localhost:9247 \
--index-name ingest-test-destination \
--username "admin" \
--password "admin" \
--use-ssl \
--batch-size-bytes 150 \
--num-threads "$max_processes"

"$SCRIPT_DIR"/env_setup/opensearch/destination_connector/test-ingest-opensearch-output.py
