#!/bin/bash
# 맥: 더블클릭하면 노트북 AI 모델 3개를 같은 과제로 비교하고, 결과 표를 브라우저로 엽니다.
# 처음에는 비교할 모델 2개(qwen3:4b 약 2.5GB, gemma3:4b 약 3.3GB)를 내려받아 시간이 걸려요.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
MODELS="qwen3:8b qwen3:4b gemma3:4b"

if [ ! -x .venv312/bin/python ]; then
  echo "❌ 먼저 run_mac.command 를 한 번 실행해 주세요. (프로그램 준비가 필요해요)"; read -r; exit 1
fi
uv pip install --python .venv312/bin/python -q -r requirements.txt 2>/dev/null

OLLAMA="$(command -v ollama || true)"
[ -z "$OLLAMA" ] && [ -x /Applications/Ollama.app/Contents/Resources/ollama ] && OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
if [ -z "$OLLAMA" ]; then
  echo "❌ Ollama가 없어요. ollama.com 에서 설치한 뒤 다시 실행해 주세요."; read -r; exit 1
fi
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  open -a Ollama 2>/dev/null || ("$OLLAMA" serve >/dev/null 2>&1 &)
  for i in $(seq 1 15); do curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
fi
for M in $MODELS; do
  if ! "$OLLAMA" list 2>/dev/null | awk '{print $1}' | grep -qx "$M"; then
    echo "▶ 비교할 모델 $M 을(를) 내려받습니다..."
    "$OLLAMA" pull "$M" || echo "⚠️ $M 을(를) 받지 못해 이 모델은 건너뜁니다."
  fi
done

echo ""
echo "🧪 비교 실험을 시작합니다. 모델마다 몇 분씩 걸려요 (전체 10~30분). 창을 닫지 마세요."
echo ""
.venv312/bin/python -m benchmark.run $MODELS
open benchmark/results/benchmark_report.html 2>/dev/null
echo ""
echo "결과 파일: benchmark/results/benchmark_report.md  ← 이 파일을 Claude에게 보내 주세요."
read -r -p "엔터를 누르면 창이 닫혀요."
