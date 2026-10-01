#!/usr/bin/env bash
# 录制 FreeCAD 对话面板的演示视频（M5 #105）：Xvfb 虚拟屏幕 + ffmpeg 录屏 + freecad_addon.gui.demo_driver。
# 用法：scripts/record_demo.sh [输出文件，缺省 demo.mp4] [--live] [其他 demo_driver 参数]
#   缺省为回放（LLM 回复预先写好，工具调用与布局真实执行）；--live 真实调用 LLM（需要 ANTHROPIC_API_KEY）。
# 需要：scripts/fetch_freecad.sh 准备的 FreeCAD、xvfb、ffmpeg。
set -euo pipefail

OUT="${1:-demo.mp4}"
shift || true
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FC="${FAP_FREECAD_ROOT:-$ROOT/.freecad/squashfs-root}"
SIZE="${FAP_DEMO_SIZE:-1600x900}"
command -v Xvfb >/dev/null || { echo "需要 Xvfb（apt-get install xvfb）" >&2; exit 2; }
command -v ffmpeg >/dev/null || { echo "需要 ffmpeg（apt-get install ffmpeg）" >&2; exit 2; }
[ -x "$FC/usr/bin/python" ] || { echo "找不到 FreeCAD：先运行 scripts/fetch_freecad.sh" >&2; exit 2; }

DISP=":$((90 + RANDOM % 9))"
Xvfb "$DISP" -screen 0 "${SIZE}x24" -nolisten tcp &
XVFB=$!
trap 'kill $XVFB 2>/dev/null || true' EXIT
sleep 1

ffmpeg -loglevel error -y -f x11grab -video_size "$SIZE" -framerate 15 -i "$DISP" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p "$OUT" &
FF=$!
sleep 1

set +e
DISPLAY="$DISP" PYTHONPATH="$FC/usr/lib:$ROOT" PYTHONUTF8=1 LANG=C.UTF-8 \
  "$FC/usr/bin/python" -m freecad_addon.gui.demo_driver "$@"
CODE=$?
set -e

kill -INT $FF 2>/dev/null || true
wait $FF 2>/dev/null || true
echo "录屏已保存：$OUT（演示退出码 $CODE）"
exit $CODE
