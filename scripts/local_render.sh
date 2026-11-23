#!/usr/bin/env bash
# Render the sample script on your laptop with Docker (no AWS needed):
#   ./scripts/local_render.sh
# Output lands in ./local-out/runs/sample/out/
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -f pipeline/Dockerfile -t yt-pipeline .
mkdir -p local-out/runs/sample
cp tests/sample_script.json local-out/runs/sample/script.json
docker run --rm -v "$PWD/local-out:/data" -e LOCAL_DIR=/data -e RUN_ID=sample yt-pipeline render
echo "Done: local-out/runs/sample/out/"

# To also test script writing locally (needs ~6 GB RAM, takes a while on CPU):
#   docker run --rm -v "$PWD/local-out:/data" -e LOCAL_DIR=/data -e RUN_ID=day1 yt-pipeline script
