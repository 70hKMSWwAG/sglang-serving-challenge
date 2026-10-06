#!/usr/bin/env bash
# Start four SGLang backends, one per GPU, ports 31000-31003.
# Radix cache stays ON (default). Logs go to logs/backend-<i>.log.
set -u
MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-0.6B}"
LOGDIR="${LOGDIR:-logs}"
SGL_PY="${SGL_PY:-/root/autodl-tmp/envs/sgl/bin/python}"
# SGLang compiles CUDA kernels at startup; ninja lives next to the interpreter.
export PATH="$(dirname "$SGL_PY"):$PATH"
mkdir -p "$LOGDIR"
for i in 0 1 2 3; do
  port=$((31000 + i))
  if curl -s "http://127.0.0.1:${port}/get_server_info" >/dev/null 2>&1; then
    echo "backend $i already running on port ${port}"
    continue
  fi
  CUDA_VISIBLE_DEVICES=$i nohup "$SGL_PY" -m sglang.launch_server \
    --model "$MODEL" \
    --host 127.0.0.1 \
    --port "$port" \
    > "$LOGDIR/backend-${i}.log" 2>&1 &
  echo "started backend $i on port ${port} (pid $!)"
done
echo "waiting for /v1/models on all four ports ..."
for i in 0 1 2 3; do
  port=$((31000 + i))
  for _ in $(seq 1 240); do
    if curl -s "http://127.0.0.1:${port}/v1/models" | grep -q '"data"'; then
      echo "backend $i ready"; break
    fi
    sleep 5
  done
done
