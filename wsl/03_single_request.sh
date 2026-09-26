#!/usr/bin/env bash
# 03_single_request.sh —— 截图1 的原始证据：/v1/models + 一次完整推理请求
#   bash /mnt/d/first-task/wsl/03_single_request.sh
set -uo pipefail
source /mnt/d/first-task/work/env.sh
source "${WSLD:-/mnt/d/first-task/wsl}/00_common.sh"
log "==================== 阶段 3/5：单次推理（截图1） ===================="

RAW="${RESD}/shot1_raw.txt"
: > "$RAW"

emit() { echo "$@" | tee -a "$RAW"; }

emit "\$ curl -s ${BASE}/v1/models | python -m json.tool"
curl -s --noproxy '*' "${BASE}/v1/models" | "${VENV}/bin/python" -m json.tool 2>&1 | tee -a "$RAW"

emit ""
emit "\$ curl -s ${BASE}/v1/chat/completions -H 'Content-Type: application/json' -d '{...}'"
REQ='{
  "model": "'"${MODEL_ID}"'",
  "messages": [
    {"role": "system", "content": "You are a concise assistant."},
    {"role": "user", "content": "用三句话说明 SGLang 的 RadixAttention 解决了什么问题。"}
  ],
  "temperature": 0.7,
  "max_tokens": 256,
  "stream": false
}'
emit "$REQ"
curl -s --noproxy '*' --max-time 600 "${BASE}/v1/chat/completions" \
     -H 'Content-Type: application/json' -d "$REQ" \
     | "${VENV}/bin/python" -m json.tool 2>&1 | tee -a "$RAW"

emit ""
emit "\$ # 流式请求（用于观测 TTFT / 逐 token 输出）"
STREAM_REQ='{"model":"'"${MODEL_ID}"'","messages":[{"role":"user","content":"Hello, what is prefix caching?"}],"max_tokens":64,"stream":true}'
{
  echo "$STREAM_REQ"
  curl -s --noproxy '*' -N --max-time 300 "${BASE}/v1/chat/completions" \
       -H 'Content-Type: application/json' -d "$STREAM_REQ" | head -c 1500
} | tee -a "$RAW"

ok "截图1 原始输出: ${RAW}"
