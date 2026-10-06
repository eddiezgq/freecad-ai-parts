#!/usr/bin/env bash
# 零件库发布（第 2 轮 L14）：从标准输入读 library.yml 打的网页包（tar.gz，内含 latest.json 和 <版本>/），
# 解包到 /opt/wenquest/factory/library。先放好版本目录，最后换 latest.json，网页不会读到半套文件。
# 只保留最近 3 个版本。用法：ssh deploy@服务器 /opt/wenquest/factory/deploy/library.sh < library-web.tar.gz
source "$(dirname "$0")/lib.sh"

tmp=$(mktemp -d "$FD/library/.incoming.XXXX")
trap 'rm -rf "$tmp"' EXIT
tar xzf - -C "$tmp"
ver=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$tmp/latest.json")
[ -d "$tmp/$ver" ] || { echo "包里没有版本目录 $ver" >&2; exit 1; }
rm -rf "library/$ver"
mv "$tmp/$ver" "library/$ver"
mv "$tmp/latest.json" library/latest.json.new
mv library/latest.json.new library/latest.json
ls -1d library/[0-9]*/ 2>/dev/null | sort -V | head -n -3 | xargs -r rm -rf
echo "零件库 $ver 已发布：$(du -sh "library/$ver" | cut -f1)；现有版本：$(ls -1 library | grep -E '^[0-9]' | tr '\n' ' ')"
