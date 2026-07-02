#!/usr/bin/env bash
# Official SWE-bench grading inside WSL, driving Docker Desktop's engine.
# Usage: grade.sh <predictions_path_wsl | gold> <run_id> <out_dir_wsl> [instance_ids...]
# Copies each instance's report.json into <out_dir_wsl>/<instance_id>.json.
set -eu
PREDICTIONS=$1
RUN_ID=$2
OUT_DIR=$3
shift 3

# Docker Desktop's engine, via the shared socket (works even when the distro's
# /var/run/docker.sock integration link is not provisioned).
if ! docker version >/dev/null 2>&1; then
  export DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock
  export PATH=/mnt/wsl/docker-desktop/cli-tools/usr/bin:$PATH
fi
docker version --format 'engine {{.Server.Version}}'

# Run from a WSL-side dir: the harness writes logs/ and reports into cwd, and
# WSL-native FS is much faster than /mnt/c.
WORKDIR=~/swebench-runs/$RUN_ID
mkdir -p "$WORKDIR"
cd "$WORKDIR"

IDS=""
if [ $# -gt 0 ]; then
  IDS="--instance_ids $*"
fi

~/swebench-venv/bin/python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --predictions_path "$PREDICTIONS" \
  --run_id "$RUN_ID" \
  --max_workers 1 \
  --cache_level env \
  $IDS

# Copy each instance's report.json back to the caller's out_dir, named by
# instance id. The model-name dir under the run_id varies (it comes from
# predictions' model_name_or_path, or "gold"), so glob over it.
mkdir -p "$OUT_DIR"
found=0
for report in "$WORKDIR"/logs/run_evaluation/"$RUN_ID"/*/*/report.json; do
  [ -f "$report" ] || continue
  iid=$(basename "$(dirname "$report")")
  cp "$report" "$OUT_DIR/$iid.json"
  found=$((found + 1))
done
echo "copied $found report(s) -> $OUT_DIR"
