#!/usr/bin/env bash
# Isolated, non-recording UI preview of the already-built Release 2D.1 image.
# Does not start a study instance, join NERDs networks, or touch the existing R2C participant.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

IMAGE="${NERDS_R2D1_PREVIEW_IMAGE:-devob_instance:r2d1-stage}"
PORT="${NERDS_R2D1_PREVIEW_PORT:-19081}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1024 || PORT > 65535)); then
  echo "ERROR: invalid local preview port: $PORT" >&2
  exit 2
fi

docker image inspect "$IMAGE" >/dev/null
python3 -m py_compile scripts/r2d1_preview_server.py

TEMP_DIR="$(mktemp -d -t nerds-r2d1-preview.XXXXXX)"
CREATED_CONTAINER=""
cleanup() {
  if [[ -n "$CREATED_CONTAINER" ]]; then
    docker rm "$CREATED_CONTAINER" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TEMP_DIR"
}
trap cleanup EXIT

mkdir -p "$TEMP_DIR/www"
CREATED_CONTAINER="$(docker create --network none --entrypoint /bin/true "$IMAGE")"
docker cp "$CREATED_CONTAINER:/home/user/www/." "$TEMP_DIR/www/"
docker cp "$CREATED_CONTAINER:/home/user/pilot1_task_descriptions.py" "$TEMP_DIR/pilot1_task_descriptions.py"
docker rm "$CREATED_CONTAINER" >/dev/null
CREATED_CONTAINER=""

PYTHONPATH="$TEMP_DIR" python3 - <<'PY' > "$TEMP_DIR/descriptions.json"
import json
from pilot1_task_descriptions import pilot1_task_description
print(json.dumps({
    task_code: {
        str(position): pilot1_task_description(task_code, position)
        for position in (1, 2)
    }
    for task_code in ("dense_v2", "lowyield_v1")
}, separators=(",", ":")))
PY

python3 scripts/r2d1_preview_server.py \
  --assets "$TEMP_DIR/www" \
  --descriptions "$TEMP_DIR/descriptions.json" \
  --port "$PORT"
