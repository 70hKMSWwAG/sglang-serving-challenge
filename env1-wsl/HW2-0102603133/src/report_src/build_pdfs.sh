#!/usr/bin/env bash
# build_pdfs.sh —— 由 HTML 源渲染出交付用的两份 PDF
#
#   report.pdf                    ← src/report_src/report.html
#   AI 使用说明情况（第二次挑战）.pdf ← src/report_src/ai_usage.html
#
# 依赖：本机已安装 Chrome（或 Edge），用其无头模式打印为 A4 PDF。
# 可用环境变量 CHROME 指定浏览器路径。
#
# 用法：
#     bash src/report_src/build_pdfs.sh          # 在 HW2-林彦超 根目录下执行
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HW2="$(cd "$HERE/../.." && pwd)"

find_chrome() {
  if [ -n "${CHROME:-}" ] && [ -x "$CHROME" ]; then echo "$CHROME"; return; fi
  for p in \
    "/c/Program Files/Google/Chrome/Application/chrome.exe" \
    "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
    "$LOCALAPPDATA/Google/Chrome/Application/chrome.exe" \
    "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
    "/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
    "$(command -v google-chrome 2>/dev/null)" \
    "$(command -v chromium 2>/dev/null)"; do
    if [ -n "$p" ] && [ -x "$p" ]; then echo "$p"; return; fi
  done
}

CHROME_BIN="$(find_chrome)"
if [ -z "$CHROME_BIN" ]; then
  echo "找不到 Chrome / Edge，请用 CHROME=<路径> 指定" >&2
  exit 1
fi
echo "使用浏览器: $CHROME_BIN"

# 先生成 report.html（数字全部取自 results/ 的原始结果）
PY="${PY:-python}"
if command -v "$PY" >/dev/null 2>&1; then
  "$PY" "$HERE/make_report.py" || { echo "make_report.py 失败" >&2; exit 1; }
else
  echo "跳过 make_report.py（未找到 python），直接使用已有的 report.html"
fi

# file:// URL 需要把路径中的中文与空格做百分号编码
to_url() {
  "$PY" -c "import pathlib,sys;print(pathlib.Path(sys.argv[1]).resolve().as_uri())" "$1" \
    2>/dev/null || echo "file://$1"
}

render() {
  local src="$1" out="$2"
  echo "--- 渲染 $(basename "$src") → $(basename "$out")"
  "$CHROME_BIN" --headless=new --disable-gpu --no-pdf-header-footer \
      --print-to-pdf="$out" "$(to_url "$src")" 2>/dev/null
  if [ -s "$out" ]; then
    echo "    OK  $out"
  else
    echo "    FAIL $out" >&2
    return 1
  fi
}

render "$HERE/report.html"   "$HW2/report.pdf"
render "$HERE/ai_usage.html" "$HW2/AI 使用说明情况（第二次挑战）.pdf"

echo
echo "完成。页数核对建议："
echo "  python -c \"import pymupdf;d=pymupdf.open('report.pdf');print('report.pdf pages:',d.page_count)\""
