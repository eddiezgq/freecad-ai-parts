#!/bin/bash
# WQ-ENCIF：综合 + 布局布线（LibreLane）+ DRC / LVS / 时序 + 版图图片，在 IIC-OSIC-TOOLS 镜像里运行（.github/workflows/chip.yml 调用）。
# 用法：run.sh REPO OUT   （REPO 只读挂载；OUT 可写）。产物：OUT/layout/*（提交进仓库的那一份）、OUT/run（完整运行目录，只作构建产物）
set -u
REPO=$1; OUT=$2
D=$REPO/factory/designs/wq-encif
W=$(mktemp -d)/wq-encif
mkdir -p "$W" "$OUT/layout"
cp -r "$D/rtl" "$D/flow" "$W/"
cd "$W/flow"
export WQ_LIBRELANE=$(librelane --version 2>&1 | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*" | head -1)
echo "LibreLane: $WQ_LIBRELANE  PDK_ROOT=${PDK_ROOT:-/foss/pdks}"
t0=$(date +%s)
librelane --manual-pdk --pdk-root "${PDK_ROOT:-/foss/pdks}" --pdk sky130A --run-tag wq --overwrite config.json > "$OUT/librelane.log" 2>&1
rc=$?
echo "LibreLane 退出码 $rc，用时 $(( $(date +%s) - t0 )) 秒"
tail -40 "$OUT/librelane.log"
R=$W/flow/runs/wq
cp -r "$R" "$OUT/run" 2>/dev/null || true
[ -d "$R/final" ] || { echo "::error title=LibreLane 没有出最终结果::退出码 $rc"; exit 1; }
CHECK=""
[ -f "$D/out/layout/result.json" ] && [ "${WQ_CHECK:-1}" = 1 ] && CHECK="--check $D/out/layout/result.json"
python3 "$W/flow/collect.py" "$R" "$OUT/layout" $CHECK; crc=$?
cp "$R"/final/gds/*.gds "$OUT/layout/wq_encif.gds"
cp "$R"/final/nl/*.nl.v "$OUT/layout/wq_encif.nl.v"
cp "$R"/final/def/*.def "$OUT/layout/wq_encif.def" 2>/dev/null || true
cp "$R"/final/sdc/*.sdc "$OUT/layout/wq_encif.sdc" 2>/dev/null || true
cp "$R"/final/metrics.json "$OUT/layout/metrics.json"
LYP=$(ls "${PDK_ROOT:-/foss/pdks}"/sky130A/libs.tech/klayout/tech/*.lyp 2>/dev/null | head -1)
python3 -c "import klayout.lay" 2>/dev/null || pip install -q --user klayout > /dev/null 2>&1
python3 "$W/flow/render.py" "$OUT/layout/wq_encif.gds" "$LYP" "$OUT/layout" > /dev/null || { echo "::error::版图图片没出来"; crc=3; }
# 第 93 轮：输入端施密特触发器的晶体管级仿真（ngspice + SKY130 模型）
LIBSP=$(ls "${PDK_ROOT:-/foss/pdks}"/sky130A/libs.tech/combined/sky130.lib.spice "${PDK_ROOT:-/foss/pdks}"/sky130A/libs.tech/ngspice/sky130.lib.spice 2>/dev/null | head -1)
mkdir -p "$OUT/transistor"
python3 "$W/flow/schmitt.py" --lib "$LIBSP" --out "$OUT/transistor"; src=$?
echo "rc=$rc collect=$crc schmitt=$src"
[ $rc = 0 ] && [ $crc = 0 ] && [ $src = 0 ]
