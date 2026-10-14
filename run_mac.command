#!/bin/bash
# 맥: 이 파일을 더블클릭하면 시연 화면이 브라우저에 열립니다.
# 컴퓨터에 설치된 Python 버전과 상관없이, 시연에 맞는 Python 3.12를 자동으로 준비합니다.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "▶ 시연 준비 중입니다. 처음 한 번은 2~3분 걸릴 수 있어요. 창을 닫지 마세요."

# 1) 설치 도우미(uv)가 없으면 설치
if ! command -v uv >/dev/null 2>&1; then
  echo "▶ 설치 도우미를 준비합니다..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# 2) 시연 전용 Python 3.12 환경 만들기 (처음 한 번만)
if [ ! -x .venv312/bin/python ]; then
  echo "▶ 시연용 Python을 준비합니다..."
  uv venv --python 3.12 .venv312 || { echo "❌ Python 준비에 실패했어요. 이 화면을 캡처해 주세요."; read -r; exit 1; }
fi

# 3) 필요한 프로그램 설치
echo "▶ 필요한 프로그램을 설치합니다..."
uv pip install --python .venv312/bin/python -q -r requirements.txt || { echo "❌ 설치에 실패했어요. 이 화면을 캡처해 주세요."; read -r; exit 1; }

# 4) Streamlit 첫 실행 때 나오는 이메일 질문 건너뛰기
mkdir -p "$HOME/.streamlit"
[ -f "$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"

# 5) 로컬 AI 준비 (Ollama 가 설치되어 있을 때만): 노트북 안에서 도는 AI 모델을 처음 한 번 내려받는다
MODEL="${LOCAL_LLM_MODEL:-qwen3:8b}"
OLLAMA="$(command -v ollama || true)"
[ -z "$OLLAMA" ] && [ -x /Applications/Ollama.app/Contents/Resources/ollama ] && OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
if [ -n "$OLLAMA" ]; then
  if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    open -a Ollama 2>/dev/null || ("$OLLAMA" serve >/dev/null 2>&1 &)
    for i in 1 2 3 4 5 6 7 8 9 10; do curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
  fi
  if ! "$OLLAMA" list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo "▶ 노트북용 AI 모델($MODEL, 약 5GB)을 처음 한 번 내려받습니다. 와이파이에서 5~15분 걸릴 수 있어요."
    "$OLLAMA" pull "$MODEL" || echo "⚠️ 모델을 받지 못했어요. 이번에는 오프라인 시연 모드로 실행합니다."
  fi
  echo "💻 로컬 AI 모드: 노트북 안의 AI($MODEL)가 에이전트의 두뇌로 일합니다."
else
  echo "ℹ️ Ollama가 없어서 오프라인 시연 모드로 실행합니다. (로컬 AI를 쓰려면 ollama.com 에서 Ollama를 설치하세요)"
fi

# 6) 시연 화면 열기
echo "▶ 시연 화면을 엽니다. 이 창은 시연이 끝날 때까지 열어 두세요."
.venv312/bin/python -m streamlit run "${APP_FILE:-app.py}" --browser.gatherUsageStats false
