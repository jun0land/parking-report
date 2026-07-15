# 클린파킹 (공모전 데모)

AI 기반 크라우드소싱 불법 주정차 자동 신고 플랫폼 데모. 서로 다른 두 시민이 각자 찍은 사진을 서버가 자동으로 병합(Data Stitching)해 신고를 완성합니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed_data.py
python wsgi.py
```

브라우저에서 http://127.0.0.1:5000 접속 후 "데모 계정으로 둘러보기"를 눌러보세요.

## 테스트

```bash
pytest
```

## 배포

PythonAnywhere 무료 플랜 배포 절차는 `DEPLOY.md`를 참고하세요.

설계 문서: `docs/superpowers/specs/2026-07-13-parking-report-design.md`
