# 가상 DRT 서버 연동

케어콜에서 예약이 확정되면 실제로 차량이 배차되고, 어르신이 문자로 받은 링크에서
차량이 오는 것을 볼 수 있게 만든 작업의 기록입니다.

- 배차 서버: `mock-drt-server` (FastAPI, 동기 SQLAlchemy)
- 예약 서비스: `drt_service` (FastAPI, 비동기)
- 브릿지: 이 프로젝트

## 1. 왜 이 연결이 필요했나

`drt_service`의 `MockDrtClient`는 배차 요청을 **항상 수락하고 `call_id`만** 돌려주는
자리표시자였습니다(`drt_client.py`의 "팀의 mock-drt-server가 아직 없어" 주석). 그래서
예약이 끝나도

- 어떤 차량이 오는지, 언제 도착하는지 알 수 없고
- 어르신이나 보호자에게 보낼 것이 없었습니다.

배차 서버가 이 공백을 정확히 채웁니다.

## 2. 왜 붙이기 쉬웠나

**두 서버의 정류장 목록이 같은 파일입니다.** `drt_service/data/stations_geo.csv`와
`mock-drt-server/data/stops.csv`가 `diff` 기준 완전히 동일합니다(사당동 20곳).
그래서 ID 매핑 없이 `str(station_id)`만 하면 통합니다.

필요·공급도 맞물립니다.

| 배차 서버가 요구 | drt_service가 이미 가진 값 |
|---|---|
| `departure_stop_id` | `plan.boarding.station_id` |
| `arrival_stop_id` | `plan.alighting.station_id` |
| `stop_to_stop_travel_seconds` | `plan.vehicle.duration_s` (ETA 모델 예측값) |

## 3. 배차 서버에 가한 변경

포트 하나로 조회 링크 주소까지 결정되도록 최소한만 손봤습니다. **테스트 43개
모두 통과합니다.**

> **2026-08-06 팀 업데이트 반영됨.** 팀이 새로 준 `mock-drt-server`의 변경 8개 파일을
> 이식했고, 아래 표의 제 수정분은 그대로 유지했습니다. 자세한 내역은 §9 참고.

| 파일 | 변경 |
|---|---|
| `app/core/config.py` | `PORT` 추가, `TRACKING_BASE_URL` 기본값을 `PORT`에서 파생, 불일치 경고 함수 |
| `app/core/lifespan.py` | 기동 시 링크 주소·리슨 포트 불일치를 로그로 경고 |
| `scripts/run_server.py` | 포트 하드코딩 제거, `--port`/`PORT` 지원 |
| `.env.example` | `PORT` 문서화, `TRACKING_BASE_URL`은 기본적으로 비워 두도록 |

## 4. drt_service에 가한 변경

원저자가 남긴 설계 의도("실제 서버가 준비되면 같은 `DrtClient` 인터페이스로 HTTP
클라이언트를 구현해 교체한다")를 그대로 따랐습니다. **6개 파일, 177줄 추가.**

| 파일 | 변경 |
|---|---|
| `app/clients/drt_client.py` | `HttpDrtClient` 추가. `DrtCallResult`에 배차 정보 필드 추가 |
| `app/reservation/confirm_reservation.py` | 차량 구간 시간 전달, 배차 정보 응답에 포함, 거절 시 예약 미저장 |
| `app/config.py` | `DRT_SERVER_BASE_URL`, `DRT_SERVER_TIMEOUT_S` 추가 |
| `app/main.py` | 설정에 따라 `HttpDrtClient` / `MockDrtClient` 선택 |
| `app/api/routes.py` | `GET /`에 `dispatch` 표시(연동 확인용) |
| `.env.example` | 새 설정 문서화 |

**기존 동작은 그대로입니다.** `DRT_SERVER_BASE_URL`이 비어 있으면 종전처럼
`MockDrtClient`로 동작하고, 기존 테스트 97개가 모두 통과합니다.

### 해결한 문제 3가지

**① 상태값 불일치 (그대로 두면 조용한 버그)**
`confirm_reservation`은 `status == "accepted"`로 성공을 판정하는데 배차 서버는
`"DISPATCHED"`를 돌려줍니다. 그대로 붙였다면 **배차가 성공해도 "거절되었습니다"라고
안내**했을 것입니다. `HttpDrtClient`가 성공 여부를 `accepted`/`rejected`로 정규화하고,
서버 원본 상태는 `dispatch_status`에 따로 담습니다.

**② 대기시간이 고정 300초였던 문제**
`expected_wait_s`는 요청자가 넣는 상수였습니다. 이제 배차 서버가 배정된 차량 위치로
실제 도착예정시간을 계산해 `estimated_arrival_s`로 돌려줍니다. `HttpDrtClient`는
`expected_wait_s`를 **쓰지 않습니다**(인터페이스 호환을 위해 파라미터만 유지).

**③ 거절 시 빈 call_id 저장**
배차 서버가 거절하면 `call_id`가 없습니다. 기존 코드는 거절도 예약으로 저장했기
때문에, 두 번째 거절에서 `call_id` 유니크 제약에 걸렸을 것입니다. 이제 거절은
예약으로 남기지 않습니다.

## 5. 브릿지에 추가한 것

| 파일 | 역할 |
|---|---|
| `bridge/notify.py` | 어르신·보호자 문자 구성과 발송기 계약(`SmsSender`) |
| `bridge/speech.py` | 도착예정시간 음성 안내, 목적지 조사(로/으로) 처리 |
| `bridge/orchestrator.py` | 예약 확정 시 문자 발송, `tracking_url` 전달 |
| `scripts/verify_dispatch.py` | 두 서버 연동만 따로 확인하는 스크립트 |

### 지켜야 했던 규칙

- **조회 링크와 호출번호는 음성으로 읽지 않습니다.** 전화로 들으신 어르신이 받아
  적을 수 없습니다. 링크는 문자로 보내고, 말로는 도착 시간만 알려 드립니다.
- **보호자 문자는 통보 동의가 확인된 경우에만** 나갑니다. 어르신의 이동 정보는
  본인 것이므로, 동의 없이 가족에게 알리지 않습니다.
- **감사 로그에 링크를 남기지 않습니다.** 링크 자체가 조회 권한이라, 발급 여부만
  기록합니다.
- 1분 미만은 "약 1분"이 아니라 "곧"이라고 말합니다. 시계를 보고 기다리시지 않도록.

## 6. 실행 방법

### 포트가 어긋나는 문제와 해결

두 서버 모두 기본 포트가 8000입니다. 더 고약한 건 배차 서버의 **리슨 포트**와
조회 링크 주소(**`TRACKING_BASE_URL`**)가 서로 독립된 설정이라는 점입니다. 둘이
어긋나면 예약은 정상으로 보이는데 **어르신이 문자를 눌러 봐야** 문제가 드러납니다.

그래서 포트를 사람이 맞추지 않도록 했습니다. `scripts/run_stack.py`는 **포트 하나만
받아 나머지를 전부 파생**시킵니다.

```
--dispatch-port 8000
   ├─► 배차 서버에 PORT=8000 을 넘김
   │      └─► 배차 서버가 TRACKING_BASE_URL = http://localhost:8000/tracking 을 파생
   └─► drt_service에 DRT_SERVER_BASE_URL = http://127.0.0.1:8000 을 넘김
```

포트를 결정하는 곳이 한 군데뿐이라 어긋날 수가 없습니다.

```bash
# 최초 1회: 네 덩어리를 한 번에 준비 (venv·의존성·DB·설정 연결)
py scripts/setup.py

# 이후에는 이 한 줄이면 둘 다 뜹니다 (Ctrl+C로 함께 내려갑니다)
py scripts/run_stack.py
py scripts/run_stack.py --dispatch-port 8100 --service-port 8101   # 포트를 옮겨도 안전
```

런처는 drt_service의 `.env`에서 릴레이 토큰을 읽어 점검에 씁니다(값은 출력하지 않습니다).

### 배차 서버 자체도 고쳤습니다

원래 `mock-drt-server`는 `scripts/run_server.py`에 포트가 8000으로 **하드코딩**되어
있었고, `TRACKING_BASE_URL`도 8000으로 고정된 별개 설정이었습니다. 그래서 포트를
옮기려면 두 곳을 손으로 맞춰야 했고, 하나만 고치면 링크가 깨졌습니다.

이제 **`PORT` 하나가 둘 다 결정합니다.**

```bash
python scripts/run_server.py               # 8000
python scripts/run_server.py --port 8100   # 링크도 자동으로 8100
PORT=8100 python scripts/run_server.py     # 환경변수로도 가능
```

- `TRACKING_BASE_URL`을 비워 두면 `http://localhost:<PORT>/tracking`으로 만들어집니다.
- 역방향 프록시나 공개 도메인을 쓸 때만 직접 지정하면 되고, 그때는 그쪽이 우선합니다.
- 직접 지정한 값이 localhost인데 포트가 실제 리슨 포트와 다르면 **기동할 때 경고**합니다.

### 4중 안전장치

포트가 어긋나도 어르신께 깨진 링크가 가지 않도록 네 겹으로 막습니다.

| 단계 | 무엇을 하나 |
|---|---|
| **설정할 때** | 배차 서버가 `PORT` 하나에서 링크 주소를 파생 → 두 곳을 맞출 일이 없음 |
| **기동할 때** | 링크 주소가 리슨 포트와 어긋나면 서버가 로그로 경고 |
| **데모 전** | `preflight.py --full`이 실제 예약을 넣어 **문자로 나갈 그 링크를 열어 봄** |
| **통화 중** | 링크가 drt_service를 가리키면 브릿지가 **문자 발송을 중단**하고 기록 |

```bash
py scripts/preflight.py           # 예약 없이 빠른 점검
py scripts/preflight.py --full    # 예약을 한 건 넣어 링크까지 확인(차량이 배차됨)
py scripts/run_stack.py --check-only
```

수동으로 띄우려면 배차 서버를 8000, drt_service를 8001에 두고 drt_service `.env`에
`DRT_SERVER_BASE_URL=http://127.0.0.1:8000`을 넣으면 됩니다.

```bash
py scripts/verify_dispatch.py     # 배차 연동만 따로
py scripts/run_handoff.py samples/03_exact_library_scheduled.json --reply "응 불러줘"
```

## 7. 실제 확인 결과

`samples/03_exact_library_scheduled.json`으로 전 구간을 관통시킨 기록입니다(2026-08-10, 실제 TMAP 키).

> 이전에는 `samples/07_exact_clinic_dispatch.json`(남현서울정형외과)을 썼지만, 실제 TMAP
> 키로 붙이면 "서울정형외과의원", "서울성모정형외과의원"처럼 이름이 비슷한 병원이 여러 곳
> 검색되어 "응 불러줘" 한 마디로 후보를 못 고르고 멈춘다(정상 동작 — 실제로 후보가 여러
> 곳이라 되묻는 것). 검색어가 유일하게 잡히는 03번 샘플로 바꿔 끊기지 않는 전 구간을
> 보여준다.

```
DRT요청 : query='사당솔밭도서관' (정확명 검색)
다솜이  : 사당솔밭도서관으로 가시는 길을 찾았어요. 남성역에서 차를 타시면 돼요.
          타고 내리는 시간까지 해서 약 3분 걸려요. 차를 불러 드릴까요?
어르신  : 응 불러줘
다솜이  : 차를 불러 드렸어요. 남성역에서 약 8분 뒤에 차가 도착해요.

[문자:어르신] DRT 예약이 완료되었습니다 / 승차 장소: 남성역 / http://localhost:8000/tracking?token=...
```

조회 링크를 열면 차량이 실제로 움직입니다(3초 간격 폴링에서 도착까지 68→63→58초).

## 8. 남은 것

| 항목 | 상태 |
|---|---|
| **문자 실제 발송** | 문구는 완성, **발송 게이트웨이 미연동**. `SmsSender`에 사업자 구현을 끼우면 됨 |
| 배차 서버 인증 | `POST /calls`에 인증이 없음. 로컬 데모는 무방하나 배포 시 필요 |
| 경로 정밀도 | `TMAP_APP_KEY`가 없으면 직선 경로로 폴백(`straight_fallback`). 키를 넣으면 실제 주행경로 |
| 차량 대수 | 기본 2대. 동시 호출 3건이면 `409`(가용 차량 없음) |
| 예약 시각 | 여전히 즉시 배차만 가능. "내일 10시" 예약은 두 서버 모두 지원하지 않음 |
| 전화망·메인 서버 | 이 작업의 범위 밖. 프레임워크에서 아직 비어 있는 두 칸 |

---

## 9. 팀 업데이트 이식 기록 (2026-08-06)

팀이 새로 준 `mock-drt-server`를 워크스페이스에 반영했습니다. 파일 추가·삭제는 없고
**8개 파일이 변경**되었으며, 제가 넣었던 수정 5개 파일은 팀이 건드리지 않아 그대로
유지했습니다(덮어쓰지 않음).

### 팀이 바꾼 것 → 이식함

| 파일 | 내용 |
|---|---|
| `app/schemas/tracking.py` | 추적 응답에 `stops: list[TrackingStop]` 추가 |
| `app/services/tracking.py` | 전체 정류장 목록을 조회해 응답에 실음 |
| `app/services/call_state.py` | **버그 수정** — 아래 설명 |
| `tests/unit/test_services_call_state.py` | 회귀 테스트 추가 (`test_stale_call_cannot_overwrite_vehicle_position`) |
| `tests/unit/test_services_tracking.py` | `stops` 검증 추가 |
| `web/tracking/app.js` | 지도에 정류장 전체 표시, 첫 렌더에서 전체가 보이도록 뷰포트 맞춤 |
| `web/tracking/index.html` | 정류장 마커 그룹 + 범례 항목 |
| `web/tracking/style.css` | 정류장 마커 스타일 |

**`call_state.py` 버그 수정 내용**: 예전에는 "완료되지 않은 모든 호출 **또는** 배차 중인
차량"을 동기화 대상으로 잡아서, 차량이 이미 다른 호출로 넘어갔는데도 **오래된 호출이
차량 위치를 덮어쓸 수 있었습니다.** 이제 `Vehicle.current_call_id == Call.id` 이면서
차량이 배차 중인 호출만 처리합니다.

### 제가 넣은 것 → 유지함 (팀 변경 없음)

`app/core/config.py`(PORT 파생 + 불일치 경고), `app/core/lifespan.py`(기동 경고),
`scripts/run_server.py`(`--port` 지원 + 접속 안내), `app/main.py`(루트 경로),
`.env.example`(PORT 문서화).

### 검증

| 항목 | 결과 |
|---|---|
| 배차 서버 테스트 | 42개 → **43개 통과** (새 회귀 테스트 포함) |
| 브릿지 테스트 | 76개 통과 |
| drt_service 테스트 | 97개 통과 |
| 추적 API 응답 | `stops`에 정류장 **20곳** 실림, 기존 필드 모두 유지 |
| 지도 화면 | 정류장 마커 **20개** 렌더링, 범례에 "정류장" 추가 확인 |
| 전 구간 | 케어콜 → 브릿지 → drt_service → 배차 → 문자 정상 |

`stops`는 **추가 필드**라 브릿지·`preflight.py`·`verify_dispatch.py`는 영향받지 않습니다.
웹 화면도 `stops`가 없으면 승·하차 두 곳만 그리도록 폴백이 있어 구버전 서버와도 호환됩니다.

---

## 10. 조회 화면 분리 이식 (2026-08-06, 두 번째) + drt-tracking-main 통합

팀이 `mock-drt-server-main (2)`에서 **조회 화면을 배차 서버 저장소 밖으로 뺐습니다**
(별도 저장소 `drt-tracking-main`, GitHub Pages + Render 배포 전제). `(2)`에는
`web/` 폴더가 아예 없고, 대신 CORS·`/health`·쿼리스트링 링크가 추가돼 있었습니다.

### 팀이 바꾼 것 → 이식함

| 파일 | 내용 |
|---|---|
| `app/main.py` | `CORSMiddleware`(`https://kt-26-team7.github.io` 허용), `/health` |
| `app/services/tracking_token.py` | `build_tracking_url()` 신설 — 링크가 `{TRACKING_BASE_URL}/{token}`(경로)에서 `{TRACKING_BASE_URL}?token={token}`(쿼리)로 변경. 기존 쿼리스트링이 있어도 보존 |
| `app/db/seed.py`, 테스트 2개 | 개행만 다름(로직 동일) |
| `tests/unit/test_services_tracking_token.py` | `build_tracking_url` 신규 테스트 2개 |

### 팀이 지운 것 → 이 워크스페이스는 다르게 대응함

팀 저장소에서는 `web/tracking/`이 통째로 사라졌지만, 이 워크스페이스는 **서버 하나로
로컬에서 전 구간을 시연하는 것**이 목적이라 화면을 아예 없애지 않았습니다. 대신
`drt-tracking-main`(팀이 준 새 프론트, Leaflet + OpenStreetMap)을 받아
`mock_drt_server/web/tracking/`에 이식했습니다.

| 무엇을 | 어떻게 |
|---|---|
| `MOCK_DRT_API_BASE_URL` (하드코딩된 `https://mock-drt-server.onrender.com`) | `window.location.origin`으로 교체 — 이 화면은 항상 배차 서버가 같은 오리진(`/static/tracking`)에서 서빙하므로, 포트를 바꿔도(run_stack.py `--dispatch-port`) 따라간다 |
| `index.html`의 `./app.js`, `./style.css` | `/static/tracking/app.js`, `/static/tracking/style.css` — 페이지가 `/tracking?token=...`(경로에 하위 세그먼트 없음)에서 열리므로 상대경로가 그대로는 깨진다 |
| `app/api/tracking.py` | 전면 재작성. `GET /tracking`(토큰 없이, 쿼리스트링은 클라이언트 JS가 읽음)이 화면을 서빙. 예전 `GET /tracking/{token}`은 `/tracking?token={token}`으로 307 리다이렉트(발송된 옛 링크 호환용). TMAP JS SDK 주입 로직은 삭제 — 새 화면은 경로 좌표를 서버 JSON(`route.coordinates`)으로 받아 Leaflet로 그리므로 브라우저에 TMAP 키를 노출할 필요가 없어짐 |

### 로컬 스크립트가 깨졌던 지점 → 고침

`scripts/preflight.py`, `scripts/verify_dispatch.py`가 `f"{tracking_url}/status"`처럼
문자열을 이어 붙여 JSON 상태 API 주소를 만들고 있었는데, 링크가 `?token=...`로
바뀌면서 `/status`가 쿼리스트링 뒤에 붙는 잘못된 주소가 됐습니다(JSON 상태 API
`/tracking/{token}/status` 자체는 경로형 그대로입니다 — 화면 링크만 바뀌었습니다).
`bridge/preflight.py`에 `tracking_status_url()`을 추가해 쿼리스트링에서 토큰을 뽑아
올바른 상태 API 주소를 다시 구성하도록 고쳤습니다.

### 검증

| 항목 | 결과 |
|---|---|
| 배차 서버 테스트 | 43개 → **45개 통과** |
| 브릿지·상태 기계 테스트 | 93개 통과(변화 없음) |
| `tracking_status_url()` | 경로형·쿼리형·타 오리진(GitHub Pages 예시) 입력 모두 수동 검증 |
| `preflight.tracking_dashboard` 프로브 | 307 리다이렉트를 따라가 200으로 화면을 받는 것 확인 |
| 조회 화면 | `run_stack.py`로 띄운 뒤 브라우저에서 Leaflet 지도·타임라인 렌더링 확인 |

---

## 11. 조회 화면 모바일 겹침 수정 + 정류장 간 소요시간 1초 기본값 제거

### 조회 화면 모바일 검증

새 조회 화면(Leaflet)을 375px 뷰포트로 렌더링해 확인한 결과, 지도 좌상단의
"TMAP 도로 경로 / 직선 경로" 배지(`.route-source`)가 Leaflet 확대·축소 버튼과
겹치는 문제를 발견했습니다(둘 다 좌상단 12px에 고정돼 있었음 — 데스크톱에서도
같은 문제였지만 지도 폭이 넓어 눈에 덜 띄었습니다). 배지를 우상단으로 옮겨
해결했고(`web/tracking/style.css`), 겹침 확인차 CSS를 재배포하며 브라우저 캐시로
옛 스타일이 계속 보이는 문제도 같이 발견해 `style.css`에도 `app.js`처럼 캐시
무효화 쿼리(`?v=20260806-2`)를 붙였습니다. 375px·1280px 모두 겹침·가로 스크롤
없음을 DOM 좌표로 확인했습니다.

### 정류장 간 DRT 소요시간이 조용히 1초로 대체되던 지점

`drt_service/app/clients/drt_client.py`의 `HttpDrtClient._travel_seconds()`가
ETA 모델 예측값(`plan.vehicle.duration_s`)이 `None`이면 **배차 서버에 보낼 값을
`MIN_STOP_TO_STOP_S`(1초)로 조용히 대체**하고 있었습니다. 정상 흐름에서는
`plan_route.py`의 `evaluate_poi()`가 `recommended_mode == "drt"`일 때 항상
`vehicle`(ETA 모델이 계산한 `Route`)을 채워 넣고, ETA 모델 자체도 30초~2시간으로
하한을 두므로(`estimate_duration.py`) 이 경로가 실제로 트리거되진 않았지만,
모델 쪽에 미래에 버그가 생기면 **배차 서버가 "차량이 정류장 사이를 1초 만에
이동했다"는 조용히 틀린 시뮬레이션을 만들어 낼 수 있는 구조**였습니다.

**요청하신 대로 고쳤습니다**: 값이 없으면 배차 서버에 아무 값도 지어내 보내지
않고, 요청 자체를 만들지 않은 채 거절(`DrtCallResult(status="rejected", ...)`)로
끝나도록 바꿨습니다(`request_call()`이 기존에 HTTP 오류·잘못된 JSON 응답을
처리하던 것과 같은 방식). 실제로 계산된 값이 배차 서버 스키마 범위(1~7200초)를
벗어나는 이상값일 때만 그 범위로 잘라 보내는데, 이건 "없는 값을 지어내는 것"이
아니라 "이미 계산된 실제값을 보호하는 것"이라 그대로 두었습니다.

`mock_drt_server/app/services/call_state.py`의 비슷해 보이는
`call.stop_to_stop_travel_seconds or 1`은 **다른 종류**입니다 — 이 필드가 스키마에
필수로 들어가기 전에 만들어진 **레거시 DB 행**을 위한 것으로,
`test_legacy_missing_travel_times_are_returned_as_null` 테스트가 이 의도를
명시하고 있어 손대지 않았습니다.

### 검증

| 항목 | 결과 |
|---|---|
| 새 테스트(`tests/test_drt_client.py`) | 3개 추가 — None 거절, 실제값 그대로 전달(142.4→142초), 이상값 클램프 |
| drt_service 테스트 | 97개 → **100개 통과** |
| 배차 서버·브릿지 테스트 | 45개·93개 유지(변경 없음) |
