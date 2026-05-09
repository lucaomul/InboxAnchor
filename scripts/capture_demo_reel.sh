#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT_DIR/docs/assets"
TMP_DIR="${TMPDIR:-/tmp}/inboxanchor-demo-capture"
URL="${1:-http://127.0.0.1:8080/demo}"
RAW_VIDEO="$TMP_DIR/inboxanchor-demo-raw.mov"

# Tuned for a 14-inch MacBook style screen and the InboxAnchor /demo route.
WINDOW_BOUNDS="{40, 40, 1320, 900}"
CAPTURE_REGION="40,52,1280,820"
DURATION_SECONDS="${DURATION_SECONDS:-18}"

mkdir -p "$OUT_DIR" "$TMP_DIR"
rm -f "$RAW_VIDEO"

osascript \
  -e 'tell application "Safari" to activate' \
  -e 'tell application "Safari" to if (count of windows) = 0 then make new document' \
  -e "tell application \"Safari\" to set URL of front document to \"$URL\"" \
  -e "tell application \"Safari\" to set bounds of front window to $WINDOW_BOUNDS"

sleep 1.5

osascript -e 'tell application "Safari" to activate' >/dev/null
screencapture -x -v -V"$DURATION_SECONDS" -R"$CAPTURE_REGION" "$RAW_VIDEO"

ffmpeg -y \
  -i "$RAW_VIDEO" \
  -vf "fps=30,scale=1200:-2:flags=lanczos,format=yuv420p" \
  -c:v libx264 \
  -movflags +faststart \
  -pix_fmt yuv420p \
  "$OUT_DIR/inboxanchor-demo.mp4"

ffmpeg -y \
  -ss 00:00:01 \
  -i "$OUT_DIR/inboxanchor-demo.mp4" \
  -frames:v 1 \
  -update 1 \
  "$OUT_DIR/inboxanchor-demo-poster.png"

ffmpeg -y \
  -i "$OUT_DIR/inboxanchor-demo.mp4" \
  -vf "fps=12,scale=1200:-2:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=full[p];[s1][p]paletteuse=dither=bayer" \
  "$OUT_DIR/inboxanchor-demo.gif"

echo "Saved:"
echo "  $OUT_DIR/inboxanchor-demo-poster.png"
echo "  $OUT_DIR/inboxanchor-demo.mp4"
echo "  $OUT_DIR/inboxanchor-demo.gif"
