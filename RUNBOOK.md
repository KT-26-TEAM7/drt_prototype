# 실행 안내서 (RUNBOOK)

케어콜 대화에서 시작해 DRT 차량이 배차되고, 어르신이 문자로 받은 링크에서 차가
오는 것을 보기까지 — 처음부터 끝까지 순서대로 실행하는 방법입니다.

여기 적힌 명령은 모두 실제로 실행해 확인한 것입니다.

---

## 0. 무엇이 무엇인가

**네 덩어리가 이 폴더 안에 모두 들어 있습니다.** 다른 폴더를 찾아다닐 필요가 없습니다.

```
2026.08.04_DRT/
├─ main_server/       ⓪ 메인 서버 — 통화를 소유하고 전체를 지휘 → 포트 8002
├─ bridge/            ① 브릿지 — 케어콜 결과를 DRT로 넘기는 접착제
├─ care_call_bot/     ④ 케어콜 대화·의도 분석 (Gemini)
├─ drt_service/       ② 정류장·경로·목적지·예약          → 포트 8001
├─ mock_drt_server/   ③ 가상 DRT 서버 — 배차·차량추적·조회페이지 → 포트 8000
├─ scripts/           실행·점검 스크립트
├─ samples/           케어콜 분석 결과 예시 7개
└─ tests/             브릿지·상태 기계 테스트
```

| # | 폴더 | 역할 | 포트 | 언제 필요한가 |
|---|---|---|---|---|
| 0 | `main_server/` | **통화 세션·대화 상태 관리, 전체 지휘** | **8002** | 통화 흐름을 볼 때 |
| 1 | `bridge/` | 게이트·검색어 변환·좌표·음성 문장·문자 | 없음 | 항상 |
| 2 | `drt_service/` | 정류장·경로·목적지·예약 | **8001** | 실서버 연동 시 |
| 3 | `mock_drt_server/` | 배차·차량 위치·조회 페이지 | **8000** | 배차까지 볼 때 |
| 4 | `care_call_bot/` | 대화·의도 분석 | 없음 | 분석기까지 붙일 때 |

**한 번에 다 필요하지는 않습니다.** 서버 없이 브릿지만으로도 전 분기를 시연할 수
있습니다(§4-1).

흐름은 이렇습니다.

```
어르신 발화 (STT 결과)
   └─► ⓪ 메인 서버  POST /call/utterance
          ├─ 대화 상태 관리 (상태 기계)
          ├─► ④ 케어콜 분석기   → 최신 한 마디만 분석
          └─► ① 브릿지          → 게이트·검색어·좌표 판단
                 └─► ② drt_service   → 정류장·경로·목적지
                        └─► ③ 배차 서버 → 차량 배정·실시간 추적·조회 링크
                               └─► 문자(어르신·보호자)
   ◄── 응답 문장 하나 (TTS로 읽어 줌)
```

**한 턴에 한 마디만 말합니다.** DRT 쪽에서 할 말이 있으면 그것만, 없으면 다솜이가
안부 대화를 잇습니다. 예전처럼 두 문단이 연달아 나가지 않습니다.

> **포트 주의는 필요 없습니다.** 배차 서버의 `PORT` 하나가 조회 링크 주소까지
> 결정하고, 런처가 그 값을 두 서버에 전달합니다. 어긋날 수 없습니다.

---

## 1. 최초 1회 준비 — 명령 하나

이 폴더에서 아래 한 줄이면 **네 덩어리가 모두 준비되고 서로 연결됩니다.**

```powershell
py scripts\setup.py
```

하는 일:

| 순서 | 내용 |
|---|---|
| 1 | 배차 서버 가상환경 + 의존성 + **DB 스키마 생성** |
| 2 | drt_service 가상환경 + 의존성 + DB 초기화 + **`.env`에 배차 서버 주소 설정** |
| 3 | 브릿지 가상환경 + 의존성 |
| 4 | 케어콜 분석기 가상환경 + 의존성 |

의존성을 내려받으므로 **몇 분 걸립니다**(drt_service의 CatBoost·LightGBM이 큼).
이미 되어 있는 단계는 건너뛰므로 여러 번 실행해도 안전합니다.

```powershell
py scripts\setup.py --check
```

설치 없이 현재 상태만 봅니다.

### 옵션

| 옵션 | 언제 |
|---|---|
| `--force` | 가상환경이 꼬였을 때. 지우고 다시 만듭니다 |
| `--check` | 상태만 확인 |

케어콜 쪽은 **의도 분석과 Gemini 대화에 필요한 것만** 설치합니다(로컬 모델 없음).

### 공통 주의 (Windows)

- 파이썬은 **`py` 런처**를 씁니다.
- 경로에 한글이 섞여 있어 `uvicorn ...`을 직접 부르면
  `Fatal error in launcher` 가 날 수 있습니다. **`python -m uvicorn ...`** 형태를 쓰세요.
  (이 문서의 명령은 모두 그렇게 되어 있습니다.)
- 콘솔에 한글이 깨지면 `$env:PYTHONUTF8 = "1"` 을 먼저 실행하세요.

### API 키는 한 번만 넣으면 됩니다

직접 넣을 곳은 **두 군데뿐**이고, 한 번 넣으면 `setup.py`를 다시 돌려도 그대로
남습니다(값이 비어 있을 때만 채우도록 되어 있습니다).

| 키 | 넣는 곳 | 없으면 |
|---|---|---|
| **TMAP** | `drt_service\.env` 의 `TMAP_APP_KEY` | 모의 장소로 검색되고 경로가 직선으로 표시됨 |
| **Gemini** | `care_call_bot\.env` 의 `GEMINI_KEY` | 분석기가 규칙 기반으로만 동작 |

나머지는 `setup.py`가 알아서 맞춥니다.

| 값 | 어떻게 |
|---|---|
| 배차 서버의 `TMAP_APP_KEY` | drt_service에 넣은 키를 복사 (**두 번 넣을 필요 없음**) |
| 브릿지의 `RELAY_API_TOKEN` | drt_service의 값을 복사 (안 맞으면 401) |
| drt_service의 `DRT_SERVER_BASE_URL` | 배차 서버 주소로 설정 |

지금 상태를 보려면:

```powershell
py scripts\setup.py --check
```

키 값은 출력하지 않고 **설정 여부와 자릿수만** 보여 주며, 서로 맞아야 하는 값이
어긋나 있으면 알려 줍니다.

> TMAP 키를 넣으면 배차 서버도 같은 키로 차량 경로를 그리므로 **호출량이 그만큼
> 늘어납니다.** 원치 않으면 `mock_drt_server\.env` 의 `TMAP_APP_KEY`를 비우면 됩니다
> (경로가 직선으로 표시될 뿐 동작에는 문제없습니다).

### 그 밖에 확인할 것

`drt_service\.env`:

| 키 | 값 | 의미 |
|---|---|---|
| `DEBUG` | `True` | 로컬 개발 |
| `RELAY_API_TOKEN` | 빈 값 또는 임의 문자열 | 값이 있으면 모든 `/api/*` 에 헤더 필요 |
| `DRT_SERVER_BASE_URL` | `http://127.0.0.1:8000` | 지우면 MOCK 배차로 돌아감 |

---

## 2. 서버 띄우기

### 2-1. 권장 — 한 줄로 둘 다

```powershell
cd "...\2026.08.04_DRT"
py scripts\run_stack.py
```

- 배차 서버 8000, drt_service 8001, **메인 서버 8002**로 띄웁니다.
- 포트를 옮기려면 `--dispatch-port 8100 --service-port 8101` 처럼 주면 되고,
  **조회 링크도 자동으로 따라갑니다.**
- 메인 서버 없이 돌리려면 `--no-main` 을 붙입니다.
- drt_service의 `.env`에서 릴레이 토큰을 읽어 점검에 씁니다(값은 출력하지 않습니다).
- 띄운 뒤 바로 사전 점검 결과를 보여 줍니다.
- **Ctrl+C** 로 세 서버가 함께 내려갑니다.

TMAP 쿼터를 쓰지 않고 돌리려면 앞에 환경변수를 붙입니다.

```powershell
$env:TMAP_APP_KEY = ""; py scripts\run_stack.py
```

정상이면 이렇게 나옵니다.

```
drt_service의 .env에서 릴레이 토큰을 읽었습니다.
서버 시작
  배차 서버        포트 8000  (mock_drt_server)
  drt_service  포트 8001  (drt_service)
  메인 서버        포트 8002  (main_server)

사전 점검
------------------------------------------------------------
  [OK  ] 포트 분리: drt_service=http://127.0.0.1:8001 / 배차=http://127.0.0.1:8000
  [OK  ] 배차 서버 응답: 차량 2대 (배차 가능 2대)
  [OK  ] drt_service 응답: DRT 위치 기반 도착지 추천 API (provider=mock)
  [OK  ] 릴레이 토큰: 인증 통과
  [OK  ] 배차 연동 설정: drt_service -> 배차 서버 연결됨
  [OK  ] 조회 대시보드 서비스: http://127.0.0.1:8000/tracking/... 에서 대시보드 확인
  [OK  ] 메인 서버 응답: 케어콜 DRT 메인 서버 (분석기=care_call_bot)
------------------------------------------------------------
  모두 정상입니다.

통화 시연: py scripts\call_demo.py --server http://127.0.0.1:8002

이제 다른 터미널에서 실행해 보세요:
  .venv\Scripts\python.exe scripts\run_handoff.py samples\03_exact_library_scheduled.json --reply "응 불러줘"
  .venv\Scripts\python.exe scripts\verify_dispatch.py

Ctrl+C로 3개 서버를 함께 내립니다.
```

> 메인 서버는 케어콜 분석기(care_call_bot)를 로딩하느라 배차 서버·drt_service보다
> 몇 초 늦게 뜹니다. `run_stack.py`가 이제 그것까지 기다렸다가 "모두 정상입니다"를
> 찍으므로, 이 메시지가 뜨면 `call_demo.py`를 바로 돌려도 됩니다.

### 2-2. 수동으로 띄우기 (터미널 2개)

런처를 쓰지 않으려면 이렇게 합니다. **배차 서버를 8000, drt_service를 8001**로 두세요.
**두 서버는 반드시 다른 터미널(다른 프로세스)에서 띄워야 하고, 같은 서버를 두 번
띄우면 안 됩니다** — 뒤에 띄운 쪽이 `WinError 10048`로 실패합니다.

터미널 1 — 배차 서버:

```powershell
cd mock_drt_server
.\.venv\Scripts\python.exe scripts\run_server.py
```

콘솔에 `Uvicorn running on http://0.0.0.0:8000` 이 뜨는데, **이 주소를 그대로 브라우저에
치면 안 됩니다.** `0.0.0.0`은 "모든 네트워크에서 받는다"는 바인딩 표시일 뿐 실제
접속 주소가 아닙니다. 바로 위에 찍히는 `[접속 안내] 브라우저에서는 http://127.0.0.1:8000 로 여세요`
를 따르세요.

포트를 옮기려면 `--port 8100` 을 붙이면 됩니다. 조회 링크 주소도 함께 따라갑니다.

터미널 2 — drt_service (`.env`의 `DRT_SERVER_BASE_URL`은 setup이 넣어 둡니다):

```powershell
cd drt_service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

연결 확인:

```powershell
curl.exe http://127.0.0.1:8001/
```

`"dispatch":"drt_server"` 면 배차 서버에 붙은 것이고, `"mock"` 이면 아직 아닙니다.

---

## 3. 제대로 물렸는지 확인

데모 전에 이걸 먼저 돌리세요. **문자로 나갈 링크가 실제로 열리는지**까지 봅니다.

```powershell
py scripts\preflight.py
```

```powershell
py scripts\preflight.py --full
```

`--full` 은 **실제로 예약을 한 건 넣어** 발급된 링크를 열어 봅니다(차량이 배차되고,
drt_service가 실제 TMAP을 쓰는 중이면 쿼터를 소모합니다 — 그 경우 경고가 먼저 뜹니다).

> 릴레이 토큰은 `setup.py`가 drt_service `.env`에서 브릿지 `.env`로 맞춰 두므로
> 따로 넘길 필요가 없습니다. 다른 값을 쓰려면 `--token` 을 주면 됩니다.

정상이면 마지막 두 줄이 이렇게 나옵니다.

```
  [OK  ] 실제 예약: CALL-60403CA1 · 차량 VEHICLE-001 · 도착예정 33초
  [OK  ] 발급된 조회 링크: 열림 · APPROACHING · DRT 1호차 · 도착까지 32초
```

이미 떠 있는 스택만 점검하려면:

```powershell
py scripts\run_stack.py --check-only
```

---

## 4. 데모 — 쉬운 것부터

### 4-1. 서버 없이 (가장 빠름, 설치 불필요)

가짜 배차 서버로 **모든 분기**를 보여 줍니다. 발표 리허설에 좋습니다.

```powershell
py scripts\run_handoff.py --all --offline --reply "응 불러줘"
```

샘플 7개가 차례로 돌아갑니다 — 정상 예약, 후보가 여러 곳, 걸어가는 게 나은 경우,
목적지 미확정, 응급, 예약 거절, 배차까지 이어지는 경우.

### 4-1-2. 통화 시연 (메인 서버) ★ 전체 흐름을 한눈에

서버를 띄운 뒤(§2-1), 전화 대신 터미널로 말을 걸어 봅니다.

```powershell
.\.venv\Scripts\python.exe scripts\call_demo.py
```

미리 짜 둔 네 가지 대화가 차례로 돌아갑니다.

| 시나리오 | 보여 주는 것 |
|---|---|
| `revoke` | **"집에 있을래" 하신 뒤 마음을 바꾸셔도 예약이 됩니다** (예전에 막히던 흐름) |
| `basic` | 목적지 → 예약 확인 → 배차 → 문자·조회 링크 |
| `emergency` | 응급 상황에서는 "차 불러줘"라고 하셔도 배차하지 않습니다 |
| `chat` | DRT와 무관한 안부 대화는 다솜이가 이어 갑니다 |

하나만 보거나 직접 대화하려면:

```powershell
.\.venv\Scripts\python.exe scripts\call_demo.py --scenario revoke
```

```powershell
.\.venv\Scripts\python.exe scripts\call_demo.py --interactive
```

> **한글이 깨지거나 `error parsing the body`가 뜨면** `curl`로 직접 한글을 보내지
> 마세요. Windows 콘솔에서 인코딩이 깨집니다. 위 스크립트(파이썬)를 쓰면 됩니다.

정해진 시나리오 없이 직접 말을 걸고, 동의 절차와 실제 음성 출력까지 보고 싶으면
§4-5의 `gemini_chat_demo.py`를 쓰세요.

### 4-2. 배차 연동만 확인

케어콜 없이 `drt_service → 배차 서버` 만 떼어 봅니다.

```powershell
.\.venv\Scripts\python.exe scripts\verify_dispatch.py
```

차량이 움직이는 것을 3초 간격으로 3번 보여 줍니다.

### 4-3. 전 구간 (케어콜 결과 → 배차 → 문자)

```powershell
.\.venv\Scripts\python.exe scripts\run_handoff.py samples\03_exact_library_scheduled.json --reply "응 불러줘"
```

> 실서버에 붙는 스크립트는 `httpx`가 필요하므로 **브릿지 venv의 python**으로 실행합니다.
> (오프라인 `--offline` 은 그냥 `py` 로 됩니다.)

> **2026-08-10 업데이트** — 이전엔 `samples\07_exact_clinic_dispatch.json`(남현서울정형외과)을
> 썼지만, 실제 TMAP 키로 붙으면 "서울정형외과의원", "서울성모정형외과의원"처럼 비슷한 이름의
> 병원이 여러 곳 검색되어 "응 불러줘" 한 마디로는 후보를 못 고르고 멈춥니다(정상 동작 —
> 후보가 실제로 여러 곳이라 되묻는 것). 전 구간을 끊기지 않고 보여 주려면 검색어가 유일하게
> 잡히는 `samples\03_exact_library_scheduled.json`(사당솔밭도서관)을 쓰세요.

기대 출력:

```
다솜이 : 사당솔밭도서관으로 가시는 길을 찾았어요. 남성역에서 차를 타시면 돼요.
         타고 내리는 시간까지 해서 약 3분 걸려요. 차를 불러 드릴까요?
어르신 : 응 불러줘
다솜이 : 차를 불러 드렸어요. 남성역에서 약 8분 뒤에 차가 도착해요.
```

보낸 문자는 `data\sent_sms.jsonl` 에 쌓입니다(**실제 발송은 아직 되지 않습니다** —
§7 참고).

### 4-4. 지도 화면 보기

`verify_dispatch.py` 나 `preflight.py --full` 이 출력한 조회 링크를 브라우저에 붙여
넣으면 차량이 움직이는 것을 볼 수 있습니다.

```
http://localhost:8000/tracking?token=<토큰>
```

> **2026-08-06 팀 업데이트로 링크 형식이 바뀌었습니다** — 예전엔 토큰이 경로였지만
> (`/tracking/<토큰>`), 지금은 쿼리스트링입니다(`/tracking?token=<토큰>`). 화면 자체도
> TMAP JS SDK 대신 **Leaflet + OpenStreetMap**으로 그리도록 바뀌어서, 조회 화면을 보는
> 브라우저는 TMAP 키가 필요 없습니다(경로 좌표는 배차 서버가 이미 계산해 JSON으로
> 내려줍니다). 예전 경로형 링크로 들어와도 배차 서버가 새 형식으로 돌려보냅니다(307).

화면에 보이는 것:

| 표시 | 내용 |
|---|---|
| 회색 점 **20개** | 사당동 정류장 전체 (2026-08-06 팀 업데이트로 추가) |
| 초록 "승" / 보라 "하" | 이번 운행의 승차·하차 정류장 |
| 파란 차량 아이콘 | 실시간 위치. 1초 간격으로 갱신됩니다 |
| 상단 카운트다운 | 승차 장소 도착까지 남은 시간 |
| 운행 진행 5단계 | 차량 배정 → 승차 장소 이동 → 차량 도착 → 목적지 이동 → 운행 완료 |

배차 서버 `.env`에 `TMAP_APP_KEY`를 넣으면 실제 도로 경로로, 없으면 직선으로 그려집니다
(화면 하단에 `TMAP 도로 경로` / `직선 경로 (TMAP 폴백)` 로 표시됩니다).

### 4-5. 케어콜 분석기까지 실제로 붙이기

발화 한 문장을 **분석기에 직접 넣어** 브릿지까지 흘려 보냅니다. 분석기 경로는
이 폴더 안의 `care_call_bot`이 기본값이라 따로 지정할 필요가 없습니다.

```powershell
.\.venv\Scripts\python.exe scripts\live_demo.py "어르신: 가까운 치과에 가려는데 차 좀 불러줘." --offline
```

`care_call_bot\.env`에 `GEMINI_KEY`가 없으면 분석기가 규칙 기반으로만 동작합니다
(경고를 출력하고 계속 진행합니다).

**실제 통화처럼(동의 절차 + 음성 출력) 보려면** 먼저 §2-1로 세 서버를 띄운 뒤
케어콜 폴더에서 실행합니다. `call_demo.py`와 달리 시나리오가 정해져 있지 않고
직접 말을 걸 수 있으며, 동의 절차를 거치고 응답을 실제 음성으로 들려줍니다.

```powershell
cd care_call_bot
.\.venv\Scripts\python.exe gemini_chat_demo.py
```

대화 상태·DRT 판단은 이 스크립트가 아니라 메인 서버가 맡습니다. 이 스크립트는
발화를 메인 서버의 `/call/utterance`로 넘기고 응답을 읽어 주기만 하는 입출력
껍데기라, 세 서버가 떠 있지 않으면 바로 종료됩니다. 음성 출력(TTS)은 macOS
내장 `say` 명령을 쓰므로 Windows에서는 텍스트로만 동작합니다.

---

## 5. 테스트

**브릿지** — 서버도 설치도 필요 없습니다(표준 라이브러리 `unittest`).

```powershell
py -m unittest discover -s tests -t .
```

**배차 서버** — `pytest`가 없으면 `.\.venv\Scripts\python.exe -m pip install pytest` 먼저.

```powershell
cd mock_drt_server; .\.venv\Scripts\python.exe -m pytest -q
```

**drt_service** — 이 PC는 pytest 기본 임시폴더에 권한 문제가 있어 `--basetemp`가 필요합니다.

```powershell
cd drt_service; .\.venv\Scripts\python.exe -m pytest -q --basetemp=C:\Temp\pt
```

현재 기준: 브릿지·상태 기계 **93개**, 배차 서버 **45개**, drt_service **100개** 모두 통과합니다.

---

## 6. 문제가 생겼을 때

| 증상 | 원인 | 해결 |
|---|---|---|
| `401 유효하지 않은 릴레이 토큰입니다` | 브릿지 `.env`의 토큰이 drt_service와 다름 | `py scripts\setup.py` 를 다시 실행하면 맞춰 줍니다 |
| 배차 서버가 뜨자마자 죽음 | DB 스키마 없음 | `py scripts\setup.py` (또는 `mock_drt_server`에서 `scripts\initialize_db.py`) |
| 무엇이 설치됐는지 모르겠음 | — | `py scripts\setup.py --check` |
| 가상환경이 꼬임 | — | `py scripts\setup.py --force` |
| `포트 8000이(가) 이미 사용 중입니다` / `WinError 10048` | **다른 창(또는 이전 실행)이 이미 그 포트를 쓰고 있음.** 같은 서버를 두 번 띄우려 한 경우가 대부분입니다 | 아래 "서버가 안 내려갈 때"로 무엇이 떠 있는지 먼저 확인하고 정리 |
| `http://0.0.0.0:8000` 접속이 안 됨(먹통처럼 보임) | `0.0.0.0`은 **바인딩 주소**(모든 인터페이스에서 받는다는 뜻)일 뿐, 브라우저로 접속할 수 있는 실제 주소가 아닙니다. uvicorn 로그에 그대로 찍혀서 헷갈리기 쉽습니다 | `http://127.0.0.1:8000` 또는 `http://localhost:8000` 으로 접속하세요. `run_server.py`가 이제 이 주소를 따로 안내합니다 |
| 배차 서버 루트(`/`)가 404 | 원래 루트 경로가 없었습니다(정상 경로는 `/vehicles`, `/stops`, `/tracking?token=...`) | 지금은 `/`도 안내 페이지를 돌려줍니다. 404가 뜨면 서버가 최신 코드로 뜬 게 맞는지 확인하세요 |
| `409 현재 이용 가능한 차량이 없습니다` | 차량 기본 2대가 모두 운행 중 | 운행이 끝나면 돌아옵니다. `.env`의 `VEHICLE_COUNT`를 늘려도 됩니다 |
| `no_feasible_destination` (목적지 못 찾음) | TMAP이 MOCK이라 모의 장소가 **정형외과·병원뿐** | `samples\07_...json` 처럼 정형외과 계열로 시연하거나 `TMAP_APP_KEY`를 넣기 |
| 응답이 `provider=mock` | `TMAP_APP_KEY`가 비어 있음 | 실제 검색이 필요하면 키를 넣고 재시작 |
| 문자 속 링크가 열리지 않음 | 조회 링크 주소와 리슨 포트 불일치 | `run_stack.py`로 띄우면 자동으로 맞습니다. 수동이면 배차 서버 `.env`의 `TRACKING_BASE_URL`을 **지우세요**(`PORT`에서 자동 생성) |
| `ModuleNotFoundError: httpx` | 실서버 스크립트를 시스템 python으로 실행 | 브릿지 venv의 python으로 실행 (§1-3) |
| `Fatal error in launcher` | 한글 경로 + `uvicorn.exe` | `python -m uvicorn ...` 형태로 실행 |
| 콘솔 한글이 깨짐 | Windows 기본 코드페이지 | `$env:PYTHONUTF8 = "1"` |
| 서버는 떴는데 `dispatch: mock` | `DRT_SERVER_BASE_URL` 미설정 | drt_service `.env`에 배차 서버 주소를 넣고 재시작 |

### 서버가 안 내려갈 때 / 포트가 이미 사용 중일 때

먼저 **무엇이 그 포트를 쓰고 있는지** 확인합니다(같은 서버를 실수로 두 번 띄운
경우가 대부분입니다).

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -State Listen |
  Select-Object LocalPort, OwningProcess,
    @{n='명령';e={(Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine}}
```

정리하려면:

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

**같은 서버가 왜 두 프로세스로 떠 있을 수 있나요?** 창을 닫지 않고 새 터미널에서
다시 실행했거나, 이전 실행이 백그라운드에 남아 있는 경우입니다. 8000/8001에서
서로 다른 서버(배차 서버·drt_service)가 하나씩 떠 있는 것은 정상이며 의도한
구성입니다 — 문제는 **같은 서버가 같은 포트에 중복으로** 뜨는 경우뿐입니다.

---

## 7. 아직 안 되는 것

| 항목 | 상태 |
|---|---|
| **문자 실제 발송** | 문구는 완성됐고 `data\sent_sms.jsonl` 에 기록됩니다. **발송 게이트웨이는 미연동** — `bridge/notify.py`의 `SmsSender`에 사업자 구현을 끼우면 됩니다 |
| 예약 시각 | "내일 오전 10시"를 받아도 **지금 배차**됩니다. 두 서버 모두 예약 일시를 지원하지 않습니다 |
| 배차 서버 인증 | `POST /calls` 에 인증이 없습니다. 로컬 데모는 무방하나 배포 시 필요 |
| 전화망 연결 | STT/TTS는 로컬 마이크·macOS 기준입니다. 전화망 진입점은 없습니다(`main_server/`는 통화를 소유·지휘하는 프로세스 자체는 이미 있고, 텍스트 발화를 대신 받습니다) |
| 안내 문장의 LLM 사용 | "차를 불러 드릴까요?" 같은 DRT 안내 문장은 LLM이 아니라 `bridge/speech.py`의 규칙 기반 템플릿이 만듭니다. LLM은 발화 의도 분석과 다솜이 안부잡담에서만 실제로 호출됩니다 |

---

## 8. 원본 폴더와의 관계 — 꼭 읽어 주세요

이 폴더의 `drt_service`, `mock_drt_server`, `care_call_bot`은 원래 있던 폴더에서
**복사해 온 것**입니다. 원본도 그대로 남아 있습니다.

| 이 폴더 | 원본 위치 | 상태 |
|---|---|---|
| `drt_service/` | `2026.07.27_DRT 알고\drt_service` | **여기가 작업본** |
| `mock_drt_server/` | `Downloads\mock-drt-server-main\...` | 여기가 작업본 |
| `care_call_bot/` | `Downloads\care-call-bot-main\...` | 여기가 작업본 |

### drt_service는 이 폴더에서만 수정합니다

`drt_service`는 팀 git 저장소라 사본이 둘이지만, **작업은 이 폴더의
`drt_service/`에서만** 합니다. 원본(`2026.07.27_DRT 알고\drt_service`)은 손대지
않습니다.

- 커밋·푸시도 이 폴더에서 합니다. 원격(`origin`, `kt-team7`)은 그대로 살아 있습니다.
- 원본 폴더는 보관용입니다. 헷갈리지 않으려면 나중에 지워도 됩니다.
- **두 폴더를 번갈아 고치지 마세요.** 내용이 갈라집니다.

```powershell
git -C drt_service status
git -C drt_service remote -v
```

### 되돌리려면

이번 통합 변경은 **커밋되지 않은 상태**입니다.

```powershell
git -C drt_service checkout -- .
```

배차 서버와 케어콜 분석기는 git 저장소가 아니므로, 원래대로 돌리려면 원본 폴더에서
다시 복사하면 됩니다.

- 배차 서버 변경 파일: `app/core/config.py`, `app/core/lifespan.py`,
  `app/main.py`, `scripts/run_server.py`, `.env.example`, `.env`
- 케어콜 분석기: **변경하지 않았습니다** (`.env`만 새로 생성)

---

## 9. 팀에서 새 버전을 받았을 때

배차 서버(`mock_drt_server`)에는 **팀 코드와 제가 넣은 개선이 섞여 있습니다.**
새 버전을 통째로 덮어쓰면 아래 기능이 사라집니다.

| 잃게 되는 것 | 증상 |
|---|---|
| `PORT` 하나로 조회 링크 주소까지 파생 | 포트를 옮기면 문자 속 링크가 깨짐 |
| 기동 시 링크·포트 불일치 경고 | 잘못된 설정을 눈치채지 못함 |
| `run_server.py --port` 지원 | 포트가 다시 8000 고정 |
| 접속 안내 문구 | `0.0.0.0` 주소로 접속 시도해 먹통처럼 보임 |
| 루트(`/`) 안내 경로 | 브라우저로 열면 404 |

### 안전하게 반영하는 절차

1. **덮어쓰지 말고 비교부터** 합니다. 새 버전과 현재 폴더에서 무엇이 다른지 봅니다.

   ```powershell
   fc /L "새버전경로\app\services\call_state.py" "mock_drt_server\app\services\call_state.py"
   ```

2. 제가 수정한 위 6개 파일을 **팀이 건드렸는지** 확인합니다. 건드리지 않았다면 그대로
   두고, 건드렸다면 양쪽 변경을 손으로 합쳐야 합니다.
3. 나머지 파일만 복사합니다.
4. 반영 후 **반드시 테스트**를 돌립니다.

   ```powershell
   cd mock_drt_server; .\.venv\Scripts\python.exe -m pytest -q
   ```

5. 제 기능이 살아 있는지 확인합니다.

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_server.py --port 8100
   ```

   `[접속 안내] ... http://127.0.0.1:8100` 이 뜨고, 발급되는 조회 링크가 `:8100` 을
   가리키면 정상입니다.

### 지난 반영 기록 (2026-08-06)

파일 추가·삭제 없이 **8개 파일 변경**이었고, 제가 수정한 6개 파일은 팀이 건드리지
않아 충돌 없이 병합했습니다.

| 팀 변경 | 내용 |
|---|---|
| `schemas/tracking.py`, `services/tracking.py` | 추적 응답에 **전체 정류장 목록**(`stops`) 추가 |
| `web/tracking/` 3개 | 지도에 정류장 20곳 표시, 뷰포트 자동 맞춤, 범례 추가 |
| `services/call_state.py` | **버그 수정** — 오래된 호출이 차량 위치를 덮어쓰던 문제 |
| 테스트 2개 | 회귀 테스트 추가 (42개 → **43개**) |

자세한 내역은 [docs/dispatch_integration.md](docs/dispatch_integration.md) §9에 있습니다.

### 지난 반영 기록 (2026-08-06, 두 번째) — 조회 화면 분리

팀이 조회 화면을 배차 서버에서 떼어 **별도 저장소(`drt-tracking-main`, GitHub
Pages + Render 배포용)**로 옮겼습니다. `mock-drt-server-main (2)`에는 `web/`
폴더가 아예 없고, 대신 CORS·헬스체크·쿼리스트링 링크가 추가돼 있었습니다.

| 팀 변경 | 반영 방식 |
|---|---|
| `app/main.py`에 `CORSMiddleware`(`kt-26-team7.github.io` 허용), `/health` | 그대로 반영. 제 6개 파일 수정분(PORT 파생 등)과 충돌 없음 |
| `services/tracking_token.py`에 `build_tracking_url()` — 링크가 `/tracking/{token}`(경로)에서 `/tracking?token=...`(쿼리)로 변경 | 그대로 반영. **로컬 데모 스크립트 3곳도 함께 고쳐야 했습니다** — 자세한 내용은 아래 |
| `web/tracking/` 삭제(별도 저장소로 이동) | **삭제하지 않음.** 이 워크스페이스는 로컬에서 서버 하나로 전 구간을 시연하는 게 목적이라, 대신 받은 `drt-tracking-main`(Leaflet+OpenStreetMap 버전)을 `web/tracking/`에 이식하고 same-origin으로 API를 부르도록 고쳤습니다 |
| `app/api/tracking.py` | 팀 변경 없음(그대로였음). 제가 직접 새 링크 형식에 맞춰 다시 씀 — 토큰 없는 `GET /tracking`이 화면을 서빙하고, 예전 `GET /tracking/{token}`은 새 형식으로 307 리다이렉트 |

**로컬 스크립트가 깨졌던 지점**: `scripts/preflight.py`, `scripts/verify_dispatch.py`가
`f"{tracking_url}/status"`처럼 문자열을 이어 붙여 JSON 상태 API 주소를 만들고
있었는데, 링크가 `?token=...`로 바뀌면서 `/status`가 쿼리스트링 뒤에 붙어 깨지는
주소가 됐습니다. `bridge/preflight.py`에 `tracking_status_url()`을 추가해 쿼리스트링에서
토큰을 뽑아 `/tracking/{token}/status`(JSON API는 여전히 경로형입니다)를 다시
구성하도록 고쳤습니다.

검증: 배차 서버 43→**45**통과(신규 `build_tracking_url` 테스트 2개), 브릿지·상태 기계
93개 유지, `run_stack.py`로 띄운 뒤 브라우저로 새 조회 화면(Leaflet 지도) 렌더링 확인.

---

## 관련 문서

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 브릿지가 무엇이고 왜 이렇게 만들었는지 |
| [docs/integration_design.md](docs/integration_design.md) | 케어콜↔DRT 필드 매핑, 알려진 갭 7가지 |
| [docs/dispatch_integration.md](docs/dispatch_integration.md) | 배차 서버 연동 상세, 각 프로젝트 변경 내역 |
| `drt_service/RUNBOOK.md` | drt_service 단독 운영 |
| `care_call_bot/README.md` | 케어콜 페르소나·모델 비교 |
