# FastAPI 운영 체크리스트

## 최초 1회

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m app.cli init-db
pytest -q
```

실제 TMAP을 사용할 때만 `.env`의 `TMAP_APP_KEY`를 설정합니다. 키가 없으면 MOCK
모드이므로 개발·테스트는 그대로 가능합니다.

## 서버 시작

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`uvicorn ...`으로 직접 실행하면 venv 경로에 한글이 섞여 길어질 때
(`Fatal error in launcher: Unable to create process...`) 실패할 수 있습니다.
`python -m uvicorn ...`을 쓰면 이 launcher exe를 거치지 않아 문제가 없습니다.

확인 순서:

1. `GET http://127.0.0.1:8000/health`
2. `http://127.0.0.1:8000/docs`에서 `/api/plan` 실행
3. 브라우저 위치가 필요하면 `http://127.0.0.1:8000/api/sender` 사용

## 정류장 CSV 갱신

```powershell
python -m app.cli import-stations
```

다른 파일을 쓰려면 `--path "C:\path\stations_geo.csv"`를 추가합니다. 동일한
`station_id`는 갱신되고 새 ID는 추가됩니다.

## ETA(정류장 간 DRT 차량 소요시간 예측) 모델

`/api/plan`, `/api/reservations`의 차량 구간 소요시간(`vehicle`)은 TMAP 실제 차량경로 대신
`app/travel_time/models/`의 CatBoost/LightGBM 모델(`app/travel_time/estimate_duration.py`)로
예측한다.

**현재 `app/travel_time/models/`의 모델은 실행 검증용 합성 데이터(59,939행)로 학습한 결과이며 운영
성능을 의미하지 않는다.** 실데이터가 도착하기 전까지는 이 수치를 운영 품질로 인용하면
안 된다. 모델을 못 읽거나 예측이 실패해도 서비스는 죽지 않고 거리 기반 공식/규칙
폴백으로 자동 전환된다(`vehicle.source`가 `*_regressor`가 아니라 `distance_formula_fallback`
등으로 표시됨).

### 실데이터로 재학습하는 절차

1. 원본 CSV를 `data/raw/eta_raw.csv`에 둔다. 필수 의미 컬럼: 출발/도착 정류장, 이동시간(초),
   날씨, 요일 또는 datetime, 속도 레벨 또는 speed_kmh. 팀원마다 컬럼명이 달라도
   `app/travel_time/preprocess_dataset.py`가 주요 별칭을 표준 컬럼으로 자동 변환한다.
2. 전처리(100만 행 규모는 청크 단위로 처리됨):
   ```powershell
   python scripts/preprocess_eta_data.py data/raw/eta_raw.csv `
     --output data/processed/eta_processed.csv `
     --stations data/stations_geo.csv
   ```
3. 학습(CatBoost/LightGBM만 비교, MAE·RMSE·R²/Accuracy·Macro F1 기준으로 자동 선정):
   ```powershell
   python scripts/train_eta_models.py data/processed/eta_processed.csv `
     --artifacts app/travel_time/models `
     --dataset-label real_eta_dataset
   ```
4. `app/travel_time/models/model_manifest.json`의 `dataset_label`이 `real_eta_dataset`으로
   바뀌었는지 확인하고, 서버를 재시작한다(기동 시 1회만 모델을 로드하므로 재학습 후에는 재시작
   필요).

## 가상 DRT 서버(mock-drt-server) 연동

`.env`의 `DRT_SERVER_BASE_URL`이 비어 있으면 종전대로 `MockDrtClient`(항상 배차 수락,
`call_id`만 반환)로 동작한다. 값을 넣으면 실제 배차 서버에 붙어 **차량 배정, 도착예정시간,
실시간 조회 링크**를 받는다.

```powershell
# .env
DRT_SERVER_BASE_URL=http://127.0.0.1:8000
```

**포트 주의**: 배차 서버도 기본 8000을 쓴다. 게다가 배차 서버의 리슨 포트와 조회 링크
주소(`TRACKING_BASE_URL`)는 서로 다른 설정이라 어긋날 수 있고, 어긋나면 사용자가 문자를
눌러 봐야 문제가 드러난다. **배차 서버를 8000에 두고 이 서비스를 8001로 옮긴다.**

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
curl.exe http://127.0.0.1:8001/     # dispatch가 drt_server인지 확인
```

포트를 손으로 맞추지 않으려면 브릿지 프로젝트(`2026.08.04_DRT`)의 런처를 쓴다. 포트
하나에서 나머지를 파생시켜 두 서버를 함께 띄우고 연결 상태까지 점검한다.

```powershell
py scripts/run_stack.py
py scripts/preflight.py --full   # 조회 링크가 실제로 열리는지까지 확인
```

연동되면 `POST /api/reservations` 응답의 `reservation`에 `vehicle_id`,
`estimated_arrival_s`, `tracking_url`, `tracking_message`가 함께 담긴다.
`expected_wait_s`(요청자가 넣는 추정 대기시간)는 이때 쓰이지 않는다 — 배차 서버가
배정된 차량 위치로 실제 도착예정시간을 계산하기 때문이다.

배차 서버가 거절하면(가용 차량 없음 등) `ok=False`, `reservation=None`으로 돌아오고
예약은 저장되지 않는다.

## MOCK 모드로 알고리즘 흐름 확인

TMAP 쿼터를 쓰지 않고 전체 흐름을 검증할 때 사용합니다. `.env`의
`TMAP_APP_KEY`를 비우면(값은 주석으로 보존) MOCK provider로 동작하며,
응답의 `provider`/`source`가 `mock`으로 표시됩니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
curl.exe http://127.0.0.1:8000/     # provider가 mock인지 확인
```

`/api/*` 호출에는 `.env`의 `RELAY_API_TOKEN` 값을 `X-Relay-Token` 헤더로
넣어야 합니다. 브라우저에서는 `/api/sender` 페이지의 릴레이 토큰 칸에
붙여넣습니다.

### 위치를 사당동으로 위조해 테스트

정류장이 사당동 일대(위도 37.4770~37.4928, 경도 126.9654~126.9848)에만
있어 **그 밖에서는 항상 `outside_service_area`가 나옵니다.** 현장에 가지
않고 확인하려면 PC 크롬에서 좌표를 위조합니다.

1. `http://127.0.0.1:8000/api/sender` 접속
2. F12 → `Ctrl+Shift+P` → "Show Sensors"
3. Location을 Custom으로 두고 위도 `37.4849`, 경도 `126.9710` 입력
4. 페이지의 버튼 클릭

localhost는 보안 컨텍스트라 이 방식은 HTTPS 없이 동작합니다.

### 폰 실측이 필요할 때 (HTTPS 터널)

브라우저 위치 API는 HTTPS에서만 동작하므로 폰으로 진짜 GPS를 쓰려면
터널이 필요합니다. Cloudflare 계정 없이 임시 주소를 받습니다.

```powershell
cloudflared tunnel --url http://localhost:8000
```

출력된 `https://....trycloudflare.com` 주소로 접속합니다. 프로세스를 끄면
주소가 사라지고 재시작하면 매번 새 주소가 나옵니다. 고정 주소가 필요하면
Cloudflare 계정과 도메인을 연결해야 합니다(1단계).

폰 실측 시 주의:

- 정확도 100m 이하, 최근 120초 이내여야 합니다(실내·지하는 422)
- 실제 사당동 안에 있어야 정상 결과가 나옵니다
- iOS는 설정 → 개인정보 보호 → 위치 서비스에서 Safari가 켜져 있어야 합니다

## 배포 (1단계)

`deploy/` 아래 템플릿을 참고합니다. 도메인·경로를 실제 값으로 바꿔야 합니다.

| 파일 | 용도 |
|---|---|
| `deploy/Caddyfile` | HTTPS 자동 발급, 경로별 레이트 리밋, 보안 헤더 |
| `deploy/drt.service` | systemd 유닛 (워커 1개 고정, 루프백 바인딩) |
| `deploy/backup-db.sh` | SQLite 온라인 백업 + 보존기간 정리 |

배포 전 확인:

- `DEBUG=False`면 `RELAY_API_TOKEN`이 비어 있을 때 **서버가 기동되지 않습니다.** 의도된 가드입니다.
- `CORS_ORIGINS`에 실제 도메인을 넣습니다(기본값에 `null`은 없습니다).
- uvicorn 워커는 1개로 유지합니다. SQLite 단일 파일을 쓰기 때문입니다.

## 자주 발생하는 문제

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError: fastapi` | 가상환경 활성화 후 `pip install -r requirements-dev.txt` |
| 응답 provider가 `mock` | `.env`의 `TMAP_APP_KEY` 확인 후 서버 재시작 |
| `401 유효하지 않은 릴레이 토큰` | `X-Relay-Token` 헤더가 `.env` 값과 같은지 확인 |
| 위치 정확도/시간 `422` | 정확도 100m 이하, 최근 120초 이내 위치를 전송 |
| 포트 사용 중 | 기존 서버를 종료하거나 `--port 8001` 사용 |
| `Fatal error in launcher: Unable to create process` | venv 경로에 한글이 섞여 길어지면 `uvicorn.exe` launcher가 깨집니다. `uvicorn ...` 대신 `python -m uvicorn ...`으로 실행 |

