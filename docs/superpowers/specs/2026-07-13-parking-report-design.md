# AI 기반 크라우드소싱 불법 주정차 자동 신고 플랫폼 — 설계 문서

- 날짜: 2026-07-13
- 목적: 공모전 제출용 데모 웹 서비스
- 배포 대상: PythonAnywhere 무료 플랜 (Flask + SQLite, 외부 API/GPU 호출 없음)

## 1. 문제 정의 및 핵심 아이디어

안전신문고 신고는 동일 위치에서 1분 간격으로 2장을 촬영해야 하므로 신고자가 현장에서 대기해야 하는 불편이 있다. 이 서비스는 서로 다른 시민이 각자 1장씩만 촬영하고 지나가면, 서버가 같은 차량(번호판 + GPS 근접)의 사진을 자동으로 병합(Data Stitching)하여 신고를 완성한다.

파파라치식 금전 보상은 설계 원칙상 제공하지 않으며, 대신 신뢰도 점수와 익명 랭킹, 동네 청정 지수를 통한 비금전적 동기부여를 사용한다.

## 2. 기술 스택 및 제약

- Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF(폼/CSRF), Pillow(이미지 리사이즈 및 EXIF 파싱)
- SQLite (PythonAnywhere 무료 플랜과 호환), Jinja2 템플릿, 모바일 우선 반응형 CSS
- 외부 API 호출 없음, GPU 없음 — GPS 거리 계산(Haversine)과 EXIF 파싱은 순수 Python으로 자체 구현
- 번호판 인식은 데모 모드에서 수동 입력 필드로 대체하며, 실서비스에서는 Vision AI(ANPR)로 대체된다는 주석을 코드에 명시

## 3. 폴더 구조

```
parking-report/
├── app/
│   ├── __init__.py            # Flask app factory
│   ├── config.py              # SQLite 경로, 업로드 폴더, 매칭 임계값 등 상수
│   ├── extensions.py          # db, login_manager 인스턴스
│   ├── models.py              # SQLAlchemy 모델
│   ├── auth/
│   │   └── routes.py          # 회원가입(+본인인증 시뮬레이션), 로그인/아웃, 데모계정 원클릭 로그인
│   ├── reports/
│   │   ├── routes.py          # 업로드, 내 신고 현황
│   │   ├── exif_utils.py      # EXIF GPS/시간 추출 + 실패시 수동입력 폴백
│   │   └── stitching.py       # Data Stitching 매칭 + AI 판독 엔진 + 신뢰도 반영
│   ├── dashboard/
│   │   └── routes.py          # 청정지수, 랭킹
│   ├── templates/
│   └── static/
│       ├── css/style.css
│       └── uploads/YYYY/MM/*.jpg   # 리사이즈된 이미지 (최대 1280px, gitignore)
├── scripts/seed_data.py       # 데모 시드 스크립트
├── tests/test_stitching.py    # 매칭/점수 로직 단위 테스트
├── instance/app.db            # SQLite (gitignore)
├── wsgi.py                    # PythonAnywhere 진입점
├── requirements.txt
├── DEPLOY.md
└── README.md
```

## 4. DB 스키마

```
Dong (행정동 마스터 - 데모용 5~8개 시드)
  id, name  (예: "역삼1동")

User
  id, username, password_hash, nickname (랭킹 노출용, unique)
  name, birthdate, phone            # 본인인증 시뮬레이션 입력값
  dong_id -> Dong                   # 가입 시 선택, 내가 올리는 신고의 귀속 동네
  trust_score (default 100)
  is_demo (bool)
  created_at

Photo (개별 시민이 올린 1장)
  id, uploader_id -> User
  plate_number                      # 데모: 수동 입력
  image_path, image_hash            # sha256, 중복 재사용(허위) 탐지용
  captured_at                       # EXIF 우선, 실패시 수동입력
  gps_source (EXIF/MANUAL), latitude, longitude
  dong_id -> Dong                   # 업로드 시점 uploader.dong_id 스냅샷
  status (PENDING/MATCHED/EXPIRED)  # 72h 미매칭 시 조회 시점에 EXPIRED 처리
  created_at

Report (Data Stitching으로 매칭된 신고 건)
  id, plate_number, dong_id
  photo_a_id, photo_b_id -> Photo   # 서로 다른 uploader 필수
  time_gap_seconds
  ai_score (0~100), ai_reason (설명가능한 판단 근거 텍스트)
  status (REVIEWING/VALID/REJECTED/FALSE)
  matched_at, resolved_at

TrustScoreLog (점수 변동 이력 - 투명성용)
  id, user_id, report_id(nullable), delta, reason, created_at
```

두 사진의 dong_id가 다를 경우(신고자가 다른 동네를 지나가다 촬영한 경우) 먼저 촬영된 사진의 dong_id를 Report의 귀속 동네로 사용한다.

## 5. Data Stitching 매칭 엔진

**매칭 조건** (사진 업로드 시 즉시 탐색):
- 같은 `plate_number`
- `status = PENDING`인 기존 사진들 중에서
- 업로더가 서로 다름 (동일인의 자작극 방지)
- GPS 거리 ≤ 50m (Haversine 공식)
- 시간차 60초 이상 ~ 72시간(3일) 이내

매칭되면 두 Photo는 `MATCHED`로 전환되고 새 `Report`가 생성되며, 즉시 AI 판독 엔진이 실행된다.

72시간 동안 매칭되지 않은 PENDING 사진은 조회 시점에 `EXPIRED`로 표시한다(별도 백그라운드 작업 없이 lazy evaluation).

## 6. AI 판독 엔진 (규칙 기반, 설명 가능)

장기 방치 차량은 매칭하되, "하루에 여러 번 짧게 정차 후 이동하는 차량(하차 등)"이 시간차만으로 매칭되어 억울하게 신고되는 것을 막기 위한 자동 판독 단계.

점수 계산 (0~100, 100에서 시작):
- 시간차가 길수록 감점 (예: 60초~6시간은 감점 거의 없음, 6~24시간 중간 감점, 24~72시간 큰 감점) — 재방문 가능성 반영
- 동일 번호판의 과거 `VALID` 이력이 있으면 가점 (상습 위반 반영)
- 동일 번호판+동일 위치 조합에서 과거에 매칭되지 못하고 `EXPIRED`된 PENDING 사진이 여러 건 있으면 감점 (짧은 정차를 반복하는 패턴 — 하차 등 반복 방문 신호)

판정:
- **점수 ≥ 70** → 즉시 `VALID` (양쪽 업로더 +5 신뢰도, 유효 신고 카운트 +1)
- **40 ≤ 점수 < 70** → `REVIEWING` 상태로 전환, 데모에서는 매칭 후 짧은 시간(예: 60초)이 지난 뒤 조회 시점에 자동으로 `REJECTED`로 종료 (증거 불충분, 무감점)
- **점수 < 40** → 즉시 `REJECTED` (무감점)

`ai_reason` 필드에 판단 근거(예: "시간차 4시간(-10), 상습 위반 이력 2건(+10), 반복 단시간 방문 이력 없음")를 사람이 읽을 수 있는 텍스트로 저장하여 UI에 투명하게 노출한다.

## 7. 허위(FALSE) 탐지 — AI 점수와 별도 로직

업로드 시점에 동일한 `image_hash`(sha256)를 가진 사진이 이미 과거에 사용된 적이 있으면(같은 사진을 재사용해 새로운 목격인 것처럼 조작 시도) 해당 업로드를 즉시 `FALSE`로 확정하고 업로더 본인에게만 -30 신뢰도 페널티를 적용한다.

이렇게 "애매해서 반려(REJECTED, 무감점)"와 "명백히 조작해서 허위(FALSE, -30)"를 명확히 분리하여, 선의로 애매한 신고를 한 사용자가 과도한 불이익을 받지 않도록 한다.

## 8. 신뢰도 점수 및 업로드 제한

- 시작 100점
- `VALID` 확정 시 photo_a, photo_b 업로더 모두 +5
- `FALSE` 확정 시 해당 업로더만 -30
- `REJECTED`는 무감점
- 일일 업로드 제한: 80점 이상 무제한, 50~79점 하루 3건, 50점 미만 하루 1건

## 9. 페이지 / 기능 흐름

- `/` 랜딩 — 서비스 소개 + "데모 계정으로 둘러보기" 버튼(원클릭 로그인)
- `/signup` — 아이디/비밀번호/닉네임/행정동 선택 + 가짜 본인인증(이름·생년월일·휴대폰 입력 → 로딩 스피너 → "인증 완료(데모용 시뮬레이션)" 배지)
- `/login`, `/logout`
- `/upload` — 사진 업로드, 번호판 수동 입력(코드 주석: 실서비스는 Vision AI ANPR로 대체), EXIF 자동 추출 실패 시 위도/경도·촬영시각 수동 입력 폼 노출
- `/my-reports` — 4개 그룹으로 표시: 매칭 대기중 / AI 검토중 / 접수완료(유효) / 반려·만료
- `/dashboard` — 행정동별 청정 지수(온도, 유효 신고 건수 기반 계산), 익명 랭킹(닉네임 + 행정동, 유효 건수 기준 Top N), 내 신뢰도 점수

## 10. 배포 및 데모 시드

- `requirements.txt`, `wsgi.py`, `DEPLOY.md`(PythonAnywhere Web 탭 설정, 가상환경 생성, 정적 파일 매핑, DB 초기화 순서 가이드 포함)
- `scripts/seed_data.py`:
  - 여러 유저(각기 다른 신뢰도 점수대 포함)
  - 여러 행정동
  - 매칭 직전 상태의 PENDING 사진(같은 번호판, 같은 위치, 아직 짝이 없는 상태)
  - 이미 VALID / REJECTED / FALSE로 처리된 과거 이력 (대시보드가 바로 그럴듯하게 보이도록)
  - 데모 계정 1개는 `is_demo=True`로 지정하여 "둘러보기" 버튼과 연결

## 11. 테스트 범위

`tests/test_stitching.py`에서 다음을 단위 테스트로 검증:
- Haversine 거리 계산 정확성
- 매칭 조건 (같은 번호판, 다른 업로더, 거리/시간 경계값)
- AI 점수 밴드별 상태 전이 (VALID/REVIEWING→REJECTED/REJECTED)
- 중복 이미지 해시 기반 FALSE 판정
- 신뢰도 점수 및 업로드 제한 로직
