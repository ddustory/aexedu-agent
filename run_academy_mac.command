#!/bin/bash
# 맥: 더블클릭하면 '학원 수업 도우미 에이전트' 화면이 열립니다. (준비 과정은 run_mac.command 와 같습니다)
cd "$(dirname "$0")"
export APP_FILE=academy_app.py
exec ./run_mac.command
