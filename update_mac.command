#!/bin/bash
# 맥: 이 파일을 더블클릭하면 GitHub의 최신 버전으로 바꾼 뒤 시연 화면을 다시 엽니다.
# (설치된 Python 환경과 .env 의 API 키는 그대로 둡니다)
cd "$(dirname "$0")"
echo "▶ 켜져 있던 시연 화면을 끕니다..."
pkill -f "streamlit run" 2>/dev/null
echo "▶ 최신 버전을 내려받습니다..."
TMP="$(mktemp -d)"
curl -fsSL https://github.com/ddustory/aexedu-agent/archive/refs/heads/main.zip -o "$TMP/main.zip" \
  || { echo "❌ 내려받지 못했어요. 인터넷 연결을 확인해 주세요."; read -r; exit 1; }
unzip -q "$TMP/main.zip" -d "$TMP"
rsync -a --exclude '.venv312' --exclude '.env' "$TMP"/aexedu-agent-main/ ./
chmod +x ./*.command
rm -rf "$TMP"
echo "✅ 최신 버전으로 바꿨어요. 시연 화면을 다시 엽니다."
exec ./run_mac.command
