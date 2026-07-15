#!/bin/bash
# PythonAnywhere 원커맨드 업데이트: 코드 갱신 + 의존성 + 데모 데이터 리셋 + 웹앱 리로드
set -e
cd "$(dirname "$0")"

git pull

PIP="$HOME/.virtualenvs/parking-venv/bin/pip"
PYTHON="$HOME/.virtualenvs/parking-venv/bin/python"
"$PIP" install -r requirements.txt --quiet
"$PYTHON" scripts/seed_data.py

# PythonAnywhere는 WSGI 파일을 touch하면 웹앱을 리로드한다
WSGI_FILE="/var/www/${USER}_pythonanywhere_com_wsgi.py"
if [ -f "$WSGI_FILE" ]; then
    touch "$WSGI_FILE"
    echo "웹앱 리로드 완료"
else
    echo "WSGI 파일을 찾지 못했습니다: $WSGI_FILE"
    echo "Web 탭에서 수동으로 Reload 버튼을 눌러주세요."
fi
echo "업데이트 완료. 데모 데이터가 초기화되었습니다 (demo / demo1234)."
