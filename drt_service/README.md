# DRT 출발 정류장 및 장소 후보 결정


## 무엇을 하는가

사용자의 현재 좌표(위도/경도)를 입력받아, DRT 정류장 중 도보로 접근 가능한
최적 승차 정류장을 결정합니다. TMAP 보행 경로 API로 실제 도보 거리·시간을
계산해 다음 규칙을 적용합니다.

- **커버리지 hard constraint**: 정류장마다 고유 반경이 있고, 그 밖의 사용자는 애초에 후보가 되지 않습니다.
- **보행 한도**: 정류장별 도보 한도와 요청의 `max_walk_m` 중 더 짧은 값을 적용합니다.
- **후보 상한(top-K)**: 직선거리가 가까운 순으로 최대 `STATION_SHORTLIST_TOP_K`곳만 실제 API를 호출합니다. 정류장이 늘어도 호출량이 선형으로 늘지 않도록 하는 상한이며, 서비스 범위 판정 자체에는 적용하지 않습니다.
- **병렬 조회**: 후보 정류장들의 보행 경로를 순차가 아니라 동시에(`STATION_ACCESS_CONCURRENCY`건씩) 조회합니다.
- **부분 실패 허용**: 후보 일부의 경로 조회가 실패해도 나머지 중 최적 정류장을 반환하고, 몇 곳이 실패했는지 함께 보고합니다.
- **전면 실패 구분**: 후보 조회가 전부 실패하면 "정류장 없음"이 아니라 별도 상태(`route_api_failed`)로 구분합니다. TMAP 장애를 "여긴 서비스 안 됨"으로 오인하지 않도록 하기 위함입니다.

## 관련 파일

```text
app/stations/find_departure_station.py   # 진입점, shortlist_stations/station_access_candidates/is_inside_service_area
app/api/routes.py                        # POST /api/stations/departure
app/schemas.py                           # DepartureStationRequest/Response
app/db/models.py                         # Station(SQLAlchemy), 정류장별 커버리지·도보한도
app/db/session.py                        # 정류장 CSV 파싱, 커버리지·도보한도 튜닝
app/clients/tmap_client.py               # Coordinate
tests/test_departure_station.py          # 단위 테스트 13개
```

## API

`POST /api/stations/departure`

요청 예시:

```json
{
  "latitude": 37.4849,
  "longitude": 126.9710,
  "accuracy": 12.5,
  "max_walk_m": 500
}
```

`max_walk_m`을 생략하면 서버 설정값(`DEFAULT_MAX_WALK_M`)이 적용되고, 실제
적용값은 응답의 `applied_max_walk_m`으로 돌아옵니다. `RELAY_API_TOKEN`이
설정된 경우 `X-Relay-Token` 헤더가 필요합니다.

응답 `status`는 네 가지입니다.

| status | 의미 |
|---|---|
| `ok` | 승차 정류장 확정 (`boarding`에 정류장과 도보 정보) |
| `outside_service_area` | 커버리지 반경 안에 정류장이 하나도 없음 |
| `no_accessible_boarding_station` | 후보는 있으나 전부 도보 한도 밖 |
| `route_api_failed` | 후보 조회가 모두 실패해 판단 불가 (재시도 대상) |

`candidate_count`/`failed_station_count`로 몇 곳을 조회했고 몇 곳이 실패했는지
확인할 수 있습니다.

응답 예시(`ok`):

```json
{
  "status": "ok",
  "boarding": {
    "station_id": 3,
    "name": "남성역",
    "station_type": "기존",
    "walk_distance_m": 17,
    "walk_duration_s": 17
  },
  "reason": null,
  "applied_max_walk_m": 500,
  "candidate_count": 5,
  "failed_station_count": 0,
  "failures": []
}
```

## 실행

이 모듈은 팀 공용 FastAPI 서버(`app/main.py`) 위에서 동작하므로, 엔드포인트를
호출하려면 서버 전체를 띄워야 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m app.cli init-db
python -m uvicorn app.main:app --reload
```

`uvicorn ...`으로 바로 실행하면 venv 폴더가 한글이 섞인 긴 경로에 있을 때
(`Fatal error in launcher: Unable to create process...`) 실패할 수 있습니다.
`python -m uvicorn ...` 형태로 실행하면 이 문제를 피할 수 있습니다.

- Swagger UI: <http://127.0.0.1:8000/docs> → `POST /api/stations/departure`
- `TMAP_APP_KEY`가 비어 있으면 `MockTmapClient`로 네트워크 없이 동작합니다.

## 테스트

```powershell
pytest tests/test_departure_station.py -v
```

`MockTmapClient`를 사용하므로 TMAP 키나 네트워크가 필요하지 않습니다. 범위 밖 판정,
도보 한도 초과, API 부분/전면 실패, 후보 상한, 병렬 조회, 결정성(동점 처리)을
검증합니다.
