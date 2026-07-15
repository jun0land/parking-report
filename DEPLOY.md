# PythonAnywhere 배포 가이드

## 1. 최초 설정

1. PythonAnywhere 대시보드 > Consoles > Bash 콘솔에서 저장소를 클론합니다.

   ```bash
   git clone <repo-url> parking-report
   cd parking-report
   ```

2. 가상환경을 만들고 의존성을 설치합니다.

   ```bash
   mkvirtualenv --python=/usr/bin/python3.10 parking-venv
   pip install -r requirements.txt
   ```

3. DB와 데모 데이터를 생성합니다.

   ```bash
   python scripts/seed_data.py
   ```

## 2. Web 앱 설정 (Web 탭)

1. "Add a new web app" > Manual configuration > Python 3.10 선택
2. Virtualenv 경로: `/home/<username>/.virtualenvs/parking-venv`
3. WSGI 설정 파일을 열어 아래 내용으로 교체합니다.

   ```python
   import sys
   path = "/home/<username>/parking-report"
   if path not in sys.path:
       sys.path.insert(0, path)

   from wsgi import app as application
   ```

4. Static files 매핑 추가: URL `/static/` → Directory `/home/<username>/parking-report/app/static/`
5. Reload 버튼을 눌러 앱을 시작합니다.

## 3. 디스크 쿼터 주의 (무료 플랜 512MB)

- `requirements.txt`에 새 패키지를 추가하기 전에 꼭 필요한지 재검토하세요. 가상환경만으로 300MB 이상을 차지할 수 있습니다.
- 시드 이미지는 스크립트가 매번 640x480 소형 JPEG로 새로 생성하므로 저장소에 커밋하지 않습니다.
- 실사용자 업로드 이미지는 저장 전 1280px로 리사이즈되도록 구현되어 있습니다(`app/reports/image_utils.py`). 이 로직을 임의로 비활성화하지 마세요.
- 디스크 사용량은 Consoles > Bash에서 `du -sh ~` 로 주기적으로 확인하세요.

## 4. 심사 기간 갱신 체크리스트 (매우 중요)

PythonAnywhere 무료 플랜은 2026-01-15 이후 생성된 계정 기준으로 **웹 앱이 마지막 Reload로부터 약 1개월 후 자동 만료**됩니다. 공모전 제출은 링크 하나로 승부하는 경우가 많으므로, 심사 도중 링크가 죽는 것이 가장 큰 리스크입니다.

- [ ] 제출 직전: Web 탭에서 앱을 한 번 Reload하여 만료 시점을 뒤로 미룹니다.
- [ ] 심사 기간 동안 최소 2주 간격으로 PythonAnywhere에 로그인해 Web 탭에서 Reload하거나 앱에 직접 접속합니다.
- [ ] 심사 결과 발표 후에도 추가 문의가 예상되면 만료 전 다시 Reload합니다.

## 5. 원커맨드 업데이트

저장소 최신 커밋으로 코드를 갱신하고, 의존성을 설치하고, 데모 데이터를 초기 상태로 리셋하고, 웹앱을 리로드하는 과정을 `update.sh` 스크립트 하나로 처리할 수 있습니다.

- 최초 1회만 실행 권한을 부여합니다.

  ```bash
  chmod +x update.sh
  ```

- 이후로는 Bash 콘솔에서 아래 한 줄만 실행하면 됩니다.

  ```bash
  ./update.sh
  ```

  내부적으로 다음을 순서대로 수행합니다.
  1. `git pull`로 최신 코드를 가져옵니다.
  2. `pip install -r requirements.txt`로 의존성을 갱신합니다.
  3. `scripts/seed_data.py`를 다시 실행해 데모 데이터를 초기 상태로 리셋합니다 (기존 DB는 덮어써집니다).
  4. WSGI 파일을 touch하여 웹앱을 자동으로 Reload합니다.

  **`update.sh`를 2주 간격으로 실행해야 하는 이유는 오직 4번 — 무료 플랜의 약 1개월 자동 만료를 막는 Reload — 때문입니다.** 위 "4. 심사 기간 갱신 체크리스트"의 주기적 Reload 요건은 이 4번으로 충족됩니다.

  반면 3번(시드 데이터 리셋)은 더 이상 "데모 신선도" 때문에 필요하지 않습니다. `app/reports/routes.py`의 `ensure_demo_hint()`가 데모 계정이 `/upload` 페이지를 열 때마다 대기 중인 PENDING 사진이 있는지 확인하고, 없으면(매칭 완료 또는 72시간 경과로 EXPIRED 처리된 경우) 자동으로 새 것을 만들어냅니다 — 즉 심사위원이 몇 명이 다녀가든, 얼마나 오래 배포해두든 "킬러 데모" 매칭이 저절로 되살아나며 재시드가 필요 없습니다. (그래도 `scripts/seed_data.py`를 다시 실행하는 것 자체는 문제 없습니다 — 그 사이 심사위원들이 만든 신고/신뢰도 점수 등 누적된 데이터를 깨끗한 초기 상태로 되돌리고 싶을 때 유용합니다.)

  주의: 스크립트는 가상환경 이름이 `parking-venv`라고 가정합니다 (`$HOME/.virtualenvs/parking-venv`), "1. 최초 설정"에서 만든 이름과 같습니다. 다른 이름을 썼다면 `update.sh` 상단의 `PIP`/`PYTHON` 경로를 맞게 수정하세요.
