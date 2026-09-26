#!/usr/bin/env bash
# 06_make_shots.sh —— 从真实运行产物里汇编出「截图1 / 截图2」的终端文本
#
# 原则：所有内容都取自真实日志与真实 HTTP 响应，不手工编造任何一行输出。
#   截图1 = 服务启动关键行 + GET /v1/models + 一次完整 chat/completions
#   截图2 = Mooncake trace 采样 + Poisson 压测的逐请求结果表
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/00_common.sh"

SLOG="${LOGD}/sglang_server.log"
RAW1="${RESD}/shot1_raw.txt"
BLOG="${LOGD}/04_benchmark.log"
OUT1="${RESD}/shot1.txt"
OUT2="${RESD}/shot2.txt"

[ -f "$SLOG" ] || die "缺少 ${SLOG}"
[ -f "$RAW1" ] || die "缺少 ${RAW1}（请先跑 03_single_request.sh）"

# ---------------------------------------------------------------- 截图1
log "汇编截图1：服务启动 + /v1/models + 单次推理"
{
  echo "\$ uname -sr && nproc"
  uname -sr; echo "$(nproc) vCPU"
  echo
  echo "# 以 OpenAI-compatible 方式在 CPU 上启动 SGLang 0.5.14"
  echo "\$ python -m sglang.launch_server --model-path ${MODEL_DIR} --device cpu --tp 1 \\"
  echo "      --host ${HOST} --port ${PORT} --trust-remote-code --disable-overlap-schedule"
  echo
  # 从真实服务日志中摘出最能说明问题的若干行（原样，不改写）
  grep -E "does not support Intel AMX|Load weight end|KV Cache is allocated|max_total_num_tokens=|Tree cache initialized|Uvicorn running on|Application startup complete" "$SLOG" \
    | sed 's/^/  /'
  echo
  echo "  # 说明：本机无 AMX/AVX-512，SGLang 自动回退 attention_backend=torch_native；"
  echo "  #       RadixCache 已启用（Tree cache initialized ... impl=RadixCache）。"
  echo
  echo "======================================================================"
  echo
  # /v1/models 的真实响应
  sed -n '1,13p' "$RAW1"
  echo "        ..."
  echo
  echo "======================================================================"
  echo
  # chat/completions：重新发起一次真实请求，用 Python 摘要关键字段（避免长 JSON 挤爆版面）
  echo "\$ curl -s ${BASE}/v1/chat/completions -H 'Content-Type: application/json' -d '"
  echo "  {\"model\":\"${MODEL_ID}\","
  echo "   \"messages\":[{\"role\":\"system\",\"content\":\"You are a concise assistant.\"},"
  echo "                {\"role\":\"user\",\"content\":\"用三句话说明 SGLang 的 RadixAttention 解决了什么问题。\"}],"
  echo "   \"max_tokens\":256,\"temperature\":0.7,\"stream\":false}'"
  curl -s --noproxy '*' --max-time 600 "${BASE}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL_ID}\",\"messages\":[{\"role\":\"system\",\"content\":\"You are a concise assistant.\"},{\"role\":\"user\",\"content\":\"用三句话说明 SGLang 的 RadixAttention 解决了什么问题。\"}],\"max_tokens\":256,\"temperature\":0.7,\"stream\":false}" \
  | "${VENV}/bin/python" -c "
import json, sys, textwrap
o = json.load(sys.stdin)
ch = o['choices'][0]
body = (ch['message'].get('content') or '').split('</think>')[-1].strip()
print()
print('  id             :', o['id'])
print('  model          :', o['model'])
print('  finish_reason  :', ch['finish_reason'])
print('  usage          :', json.dumps(o['usage'], ensure_ascii=False))
print('  回答正文（截断显示）:')
for ln in textwrap.wrap(body, 64)[:6]:
    print('     ', ln)
" 2>&1
} > "$OUT1"

# 追加一次更易读的「短请求」真实往返，作为单次推理的补充佐证
{
  echo
  echo "--- 补充：一次短提示的真实往返（便于观察 TTFT 与 token 统计） ---"
  echo "\$ curl -s ${BASE}/v1/completions -H 'Content-Type: application/json' \\"
  echo "      -d '{\"model\":\"${MODEL_ID}\",\"prompt\":\"Count from 1 to 50.\",\"max_tokens\":64,\"ignore_eos\":true}'"
  RESP=$(curl -s --noproxy '*' --max-time 300 "${BASE}/v1/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL_ID}\",\"prompt\":\"Count from 1 to 50.\",\"max_tokens\":64,\"temperature\":0,\"ignore_eos\":true}")
  echo "$RESP" | "${VENV}/bin/python" -c "
import json,sys
o=json.load(sys.stdin)
print('  choices[0].text :', repr(o['choices'][0]['text'])[:120] + ' ...')
print('  finish_reason   :', o['choices'][0]['finish_reason'])
print('  usage           :', json.dumps(o['usage']))
" 2>&1
} >> "$OUT1"
ok "截图1 文本: $OUT1"

# ---------------------------------------------------------------- 截图2
log "汇编截图2：Mooncake trace 采样 + Poisson 压测"
# 压测日志较长，纵向放不进单页 A4，故拆为两段：a=参数与逐请求过程，b=汇总统计
"${VENV}/bin/python" - "$BLOG" "${RESD}/shot2a.txt" "${RESD}/shot2b.txt" <<'PY'
import re, sys
log = open(sys.argv[1], encoding="utf-8").read().splitlines()
# a 段：直到最后一条逐请求日志行（形如 "  [20/20] req#17 ..."）
idx_a = max(i for i, l in enumerate(log) if re.match(r"\s*\[\s*\d+/\d+\]", l))
# b 段：从 a 段之后的第一条分隔线（表格前的 "====..."）开始
idx_b = next(i for i in range(idx_a, len(log)) if set(log[i].strip()) == {"="})

head = ["$ python 04_benchmark.py --n 20 --mean-interval 2.0 "
        "--input-cap 1024 --out-cap 64 --seed 2026", ""]
a = head + log[:idx_a + 1]
b = ["$ # ---- 承上：逐请求结果汇总与统计 ----", ""] + log[idx_b:]
for path, lines in ((sys.argv[2], a), (sys.argv[3], b)):
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"  {path}: {len(lines)} 行")
PY
ok "截图2 文本: ${RESD}/shot2a.txt + ${RESD}/shot2b.txt"

echo
log "完成。下一步用 tools/make_shot.py 渲染为 PNG。"
wc -l "$OUT1" "$OUT2"
