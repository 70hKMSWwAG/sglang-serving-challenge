#!/usr/bin/env bash
# 下载 Mooncake FAST'25 arxiv-trace 到 HW1/data/mooncake_trace.jsonl（约 4.4 MB，23,608 行）
# 沙箱内直连 raw.githubusercontent.com 不通时，使用 gh-proxy 镜像。
set -e
DEST="$(dirname "$0")/../data/mooncake_trace.jsonl"
mkdir -p "$(dirname "$DEST")"
URLS=(
  "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl"
  "https://gh-proxy.com/https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl"
  "https://ghfast.top/https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl"
)
for u in "${URLS[@]}"; do
  echo "try $u"
  if curl -fL --connect-timeout 15 --max-time 300 -o "$DEST" "$u"; then
    echo "saved -> $DEST ($(wc -l < "$DEST") lines)"; exit 0
  fi
done
echo "all mirrors failed" >&2; exit 1
