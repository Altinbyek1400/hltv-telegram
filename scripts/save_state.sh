#!/usr/bin/env bash
# state.json-г repo руу буцааж хадгална.
#
# Хоёр ажил зэрэг ажиллавал rebase мөргөлддөг тул merge хийхийн оронд:
#   1. өөрийн state-ээ түр хадгална
#   2. remote-ийн хамгийн сүүлийн байдал руу шууд шилжинэ
#   3. хоёр state-ийг нэгтгэнэ (аль нэгийг нь алдахгүй)
#   4. push хийнэ, амжилтгүй бол дахин оролдоно
set -euo pipefail

BRANCH="${BRANCH:-main}"

if [ ! -f state.json ]; then
  echo "state.json алга — хадгалах зүйлгүй."
  exit 0
fi

if [ -z "$(git status --porcelain state.json)" ]; then
  echo "Төлөв өөрчлөгдөөгүй."
  exit 0
fi

cp state.json /tmp/mine.json
git config user.name  "cs2-bot"
git config user.email "cs2-bot@users.noreply.github.com"

for attempt in 1 2 3 4 5; do
  git fetch origin "$BRANCH"
  git reset --hard "origin/$BRANCH"

  python3 - <<'PY'
import json, pathlib

mine = json.loads(pathlib.Path("/tmp/mine.json").read_text(encoding="utf-8"))
target = pathlib.Path("state.json")
theirs = {}
if target.exists():
    try:
        theirs = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        theirs = {}

for key in ("announced", "started", "finished"):
    mine[key] = {**theirs.get(key, {}), **mine.get(key, {})}

if theirs.get("daily") and not mine.get("daily"):
    mine["daily"] = theirs["daily"]

target.write_text(json.dumps(mine, ensure_ascii=False, indent=1), encoding="utf-8")
PY

  if [ -z "$(git status --porcelain state.json)" ]; then
    echo "Remote дээрх төлөв аль хэдийн шинэ байна."
    exit 0
  fi

  git add state.json
  git commit -m "state: $(date -u +%Y-%m-%dT%H:%MZ)"

  if git push origin "HEAD:$BRANCH"; then
    echo "Төлөв хадгалагдлаа ($attempt дэх оролдлого)."
    exit 0
  fi

  echo "Push амжилтгүй, дахин оролдоно..."
  sleep $(( (RANDOM % 8) + 4 ))
done

echo "Төлөв хадгалж чадсангүй." >&2
exit 1
