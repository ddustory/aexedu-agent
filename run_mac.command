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

# 5) 시연 화면 열기
echo "▶ 시연 화면을 엽니다. 이 창은 시연이 끝날 때까지 열어 두세요."
.venv312/bin/python -m streamlit run app.py --browser.gatherUsageStats false
