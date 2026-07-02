#!/usr/bin/env bash
# Official SWE-bench grading inside WSL, driving Docker Desktop's engine.
# Usage: grade.sh <predictions_path_wsl> <run_id> [instance_ids...]
set -eu
PREDICTIONS=$1
RUN_ID=$2
shift 2

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

echo "=== report files ==="
ls -la ./*.json 2>/dev/null || true
for f in ./*"$RUN_ID"*.json; do
  [ -f "$f" ] && echo "--- $f" && cat "$f"
done
