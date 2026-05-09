#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT_DIR/docs/assets"
TMP_DIR="${TMPDIR:-/tmp}/inboxanchor-demo-capture"
URL="${1:-http://127.0.0.1:8080/demo}"

# Tuned for a 14-inch MacBook style screen and the InboxAnchor /demo route.
WINDOW_BOUNDS="{40, 40, 1320, 900}"
CAPTURE_REGION="40,52,1280,820"
FRAME_COUNT="${FRAME_COUNT:-22}"
FRAME_INTERVAL="${FRAME_INTERVAL:-0.8}"

mkdir -p "$OUT_DIR" "$TMP_DIR"
setopt NULL_GLOB
rm -f "$TMP_DIR"/frame-*.png

osascript \
  -e 'tell application "Safari" to activate' \
  -e 'tell application "Safari" to if (count of windows) = 0 then make new document' \
  -e "tell application \"Safari\" to set URL of document 1 to \"$URL\"" \
  -e "tell application \"Safari\" to set bounds of front window to $WINDOW_BOUNDS"

sleep 1.5

for index in $(seq 0 $((FRAME_COUNT - 1))); do
  frame_name=$(printf "frame-%02d.png" "$index")
  osascript -e 'tell application "Safari" to activate' >/dev/null
  screencapture -x -R"$CAPTURE_REGION" "$TMP_DIR/$frame_name"
  sleep "$FRAME_INTERVAL"
done

cp "$TMP_DIR/frame-00.png" "$OUT_DIR/inboxanchor-demo-poster.png"

ffmpeg -y \
  -framerate 1.25 \
  -i "$TMP_DIR/frame-%02d.png" \
  -vf "scale=1200:-2:flags=lanczos,format=yuv420p" \
  -c:v libx264 \
  -pix_fmt yuv420p \
  "$OUT_DIR/inboxanchor-demo.mp4"

ffmpeg -y \
  -framerate 1.25 \
  -i "$TMP_DIR/frame-%02d.png" \
  -vf "fps=10,scale=1200:-2:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=full[p];[s1][p]paletteuse=dither=bayer" \
  "$OUT_DIR/inboxanchor-demo.gif"

echo "Saved:"
echo "  $OUT_DIR/inboxanchor-demo-poster.png"
echo "  $OUT_DIR/inboxanchor-demo.mp4"
echo "  $OUT_DIR/inboxanchor-demo.gif"
