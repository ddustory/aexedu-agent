#!/bin/bash
# 맥: 이 파일을 더블클릭하면 시연 화면이 브라우저에 열립니다.
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
streamlit run app.py
