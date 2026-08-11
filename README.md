# 케어콜 → DRT 통합 작업공간

어르신과의 안부 통화에서 이동 의도를 알아내고, DRT 차량을 실제로 배차하고, 문자로
받은 링크에서 차가 오는 것을 보기까지 — **다섯 조각이 이 폴더 안에 모두 들어 있습니다.**

```
2026.08.04_DRT/
├─ main_server/       ⓪ 메인 서버 — 통화를 소유하고 전체를 지휘         → 포트 8002
├─ bridge/            ① 브릿지 — 케어콜 결과를 DRT로 넘기는 접착제 (이 프로젝트의 본체)
├─ care_call_bot/     ④ 케어콜 대화·의도 분석 (Gemini)
├─ drt_service/       ② 정류장·경로·목적지·예약              → 포트 8001
└─ mock_drt_server/   ③ 가상 DRT 서버 — 배차·차량추적·조회페이지 → 포트 8000
```

준비와 실행은 각각 명령 하나입니다.

```bash
py scripts/setup.py      # 다섯 조각 준비 + 서로 연결 (최초 1회)
py scripts/run_stack.py  # 배차 서버·drt_service·메인 서버 세 개를 올바른 포트로 함께 띄우기
```

자세한 절차는 **[RUNBOOK.md](RUNBOOK.md)** 를 보세요.
어느 폴더에서 작업해야 하는지 헷갈리면 **[폴더_안내.md](폴더_안내.md)** 를 보세요.

> **실제 전화(ClawOps)로 어르신께 걸 수 있게 하려면** 클라우드(Render) 배포가
> 필요합니다 — `mcp_server/`(신규, ClawOps 에이전트가 통화 중 호출하는 MCP 도구
> 서버)와 배포 방법은 [docs/cloud_deployment.md](docs/cloud_deployment.md)를 보세요.
> 이 README와 RUNBOOK.md는 로컬 실행만 다룹니다.

---

## 브릿지가 하는 일

분석기는 JSON을 만들어 화면에 찍기만 했고, DRT 서비스는 좌표와 검색어를 받을 준비만
되어 있었습니다. 브릿지가 그 사이를 잇습니다.

```
어르신 발화
   │
   ▼  care-call-bot / drt_analyzer.analyze_conversation()
분석 결과 JSON  ── dialogue_stage, destination_category, search_mode, missing_slots ...
   │
   ▼  이 브릿지
   │   ① 게이트   호출해도 되는 상태인가        bridge/gate.py
   │   ② 검색어   무엇을 찾을 것인가            bridge/mapping.py
   │   ③ 좌표     어디서 타실 것인가            bridge/location.py
   │   ④ 호출     POST /api/plan, /api/reservations
   │   ⑤ 문장     뭐라고 말씀드릴 것인가        bridge/speech.py
   │   ⑥ 문자     조회 링크를 누구에게 보낼까    bridge/notify.py
   ▼
"사당솔밭도서관으로 가시는 길을 찾았어요. 남성역에서 차를 타시면 돼요. 차를 불러 드릴까요?"
   │  "응 불러줘"
   ▼  drt_service ──► 가상 DRT 서버(mock-drt-server): 차량 배차·위치 추적
"차를 불러 드렸어요. 남성역에서 곧 차가 도착해요."
   └─ 문자: 어르신·보호자에게 실시간 조회 링크
```

배차 서버까지 연결하는 방법은 [docs/dispatch_integration.md](docs/dispatch_integration.md)를 보세요.

## 브릿지는 케어콜 분석기를 import하지 않습니다

메인 서버(`main_server/`)는 브릿지(`bridge/`)와 케어콜 분석기(`care_call_bot/drt_analyzer.py`)를
**둘 다 같은 파이썬 프로세스 안에서 직접 import**합니다 — 그래야 전화 한 통이 분석부터
배차·문자까지 사람이 중간에 스크립트를 돌려 주지 않아도 자동으로 끝까지 이어집니다.

다만 **브릿지 자신은 `care_call_bot`을 import하지 않고, 분석기의 출력 JSON만을 계약**으로
삼습니다. 그쪽은 Gemini 의존성과 macOS 전용 TTS 코드를 가지고 있어서, 브릿지가 그걸
직접 import하면 브릿지 테스트도 그 환경(API 키 등)에 묶이기 때문입니다. 덕분에

- 분석기 출력 필드가 일부 빠져 있어도 기본값으로 흡수하고,
- 분석기 내부 구현이 바뀌어도 브릿지는 영향을 받지 않으며,
- 네트워크·모델 없이 브릿지 테스트가 돌아갑니다(93개, 0.3초).

| 무엇이 | 무엇을 | 어떻게 |
|---|---|---|
| 메인 서버 | 브릿지 | 같은 프로세스 (Python import) |
| 메인 서버 | 케어콜 분석기(`drt_analyzer.py`) | 같은 프로세스 (동적 import, `main_server/analyzer.py`) |
| 브릿지 | drt_service | HTTP (`/api/plan`, `/api/reservations`) |
| drt_service | 배차 서버 | HTTP (`POST /calls`) |
| 브릿지 | 케어콜 분석기 | **출력 JSON만** (import 없음 — 계약이지 연결이 아님) |
| (클라우드) `mcp_server` | 메인 서버 | HTTP (`X-Call-Token` 인증) — ClawOps 전화 연동용, [docs/cloud_deployment.md](docs/cloud_deployment.md) 참고 |

> 처음부터 순서대로 실행하는 방법은 **[RUNBOOK.md](RUNBOOK.md)** 를 보세요.

## 빠르게 확인하기

drt_service를 띄우지 않고, 가짜 DRT 서버로 전체 분기를 볼 수 있습니다.

```bash
py scripts/run_handoff.py --all --offline --reply "응 불러줘"
```

테스트 실행 (추가 설치 없이 표준 라이브러리만 사용):

```bash
py -m unittest discover -s tests -t .
```

## 실제 서버에 붙이기

`py scripts/setup.py` 가 준비와 연결(릴레이 토큰 맞춤 포함)을 모두 해 둡니다.
서버를 띄운 뒤 **브릿지 가상환경의 python**으로 실행하면 됩니다.

```bash
py scripts/run_stack.py
```

```bash
.venv\Scripts\python.exe scripts\run_handoff.py samples\03_exact_library_scheduled.json --reply "응 불러줘"
```

분석기까지 한 번에 이어 보려면(경로 지정 불필요 — 이 폴더의 `care_call_bot`이 기본값):

```bash
.venv\Scripts\python.exe scripts\live_demo.py "어르신: 가까운 치과에 가려는데 차 좀 불러줘."
```

## 케어콜 쪽에 붙이는 방법

`care_call_bot/gemini_chat_demo.py`가 실제 연결 지점입니다. 분석·상태 관리·DRT
판단은 전부 메인 서버(`main_server/app.py`)가 맡고, 이 스크립트는 발화를 메인
서버의 `/call/utterance`에 넘긴 뒤 돌아온 `reply`를 화면에 찍고 TTS로 읽어 주는
**입출력 껍데기**입니다.

```python
started = post(f"{server}/call/start", {"user_id": user_id})
session_id = started["session_id"]
speak(started["reply"])                    # 다솜이의 첫인사

reply = post(f"{server}/call/utterance", {"session_id": session_id, "text": user_input})
speak(reply["reply"])                       # 이번 턴에 할 말(DRT 안내 또는 안부 대화)
```

`py scripts\run_stack.py`로 세 서버를 띄운 뒤 `cd care_call_bot && .venv\Scripts\python.exe gemini_chat_demo.py`로 바로 시도해 볼 수 있습니다.
`--voice`를 붙이면 키보드 대신 마이크로 말할 수 있습니다(STT: faster-whisper).

**실제 전화로 걸려오는 통화**는 이 스크립트가 아니라 `mcp_server/`(ClawOps 에이전트가
통화 중 호출하는 MCP 도구 서버)를 거칩니다 — 같은 메인 서버 API를 그대로 재사용하는
얇은 어댑터입니다. 자세한 내용은 [docs/cloud_deployment.md](docs/cloud_deployment.md)를 보세요.

## 구성

| 파일 | 역할 |
|---|---|
| `main_server/app.py` | 통화 세션 소유, 대화 상태 관리, 브릿지·분석기 지휘 (`/call/*` API) |
| `main_server/analyzer.py` | `care_call_bot/drt_analyzer.py`를 동적 import하는 어댑터 |
| `bridge/contract.py` | 분석 결과 JSON을 표준 형태로. 빠진 필드 흡수, 사라진 정확명 복원 |
| `bridge/gate.py` | DRT를 불러도 되는 상태인지 판정 (응급·거절·정보부족 차단) |
| `bridge/mapping.py` | `search_mode` → `query`/`is_specific` 변환 |
| `bridge/location.py` | 등록 자택 좌표 확보 + 위치정보 이용 동의 확인 |
| `bridge/drt_client.py` | drt_service HTTP 호출 (`X-Relay-Token` 인증) |
| `bridge/speech.py` | 응답 → 음성용 한국어 문장 (영어·한자·이모지 규칙 적용) |
| `bridge/session.py` | 되물음 상태 유지, 어르신 답변 해석("연세치과로 가자") |
| `bridge/notify.py` | 예약 확정 문자 구성(어르신·보호자), 발송기 계약 |
| `bridge/preflight.py` | 서버들이 제대로 물려 있는지 판정 |
| `bridge/orchestrator.py` | 위 전부를 엮는 진입점 |
| `bridge/fake_service.py` | drt_service 없이 전 분기를 시연하는 가짜 서버 |
| `mcp_server/server.py` | ClawOps 전화 연동용 MCP 도구 3개(`start_call`/`send_utterance`/`end_call`) |
| `scripts/run_stack.py` | 배차 서버·drt_service·메인 서버 세 개를 올바른 포트로 함께 띄움 |
| `scripts/preflight.py` | 데모 전 점검(`--full`은 링크까지 열어 봄) |
| `scripts/verify_dispatch.py` | drt_service ↔ 배차 서버 연동만 따로 확인 |

## 배차 서버까지 함께 띄우기

두 서버 모두 기본 포트가 8000이고, 배차 서버의 조회 링크 주소는 리슨 포트와
**별개의 설정**이라 어긋날 수 있습니다. 어긋나면 어르신이 문자를 눌러 봐야 문제가
드러납니다. 그래서 포트를 사람이 맞추지 않게 했습니다.

```bash
py scripts/run_stack.py          # 포트 하나에서 나머지를 파생시켜 둘 다 띄움
py scripts/preflight.py --full   # 문자로 나갈 링크를 실제로 열어 확인
```

자세한 내용은 [docs/dispatch_integration.md](docs/dispatch_integration.md)를 보세요.

설계 근거와 남은 과제는 [docs/integration_design.md](docs/integration_design.md)에 정리했습니다.

## 안전 규칙

브릿지가 **DRT를 절대 부르지 않는** 경우입니다. 테스트로 고정해 두었습니다.

- 응급 표현이 있을 때 (`emergency_risk`) — 배차보다 보호자·119 연결이 먼저입니다
- "차는 안 불러도 돼"처럼 거절하셨을 때
- 차량 호출 동의가 아직 없을 때 — 동의 없이 TMAP 쿼터를 쓰지 않습니다
- 목적지가 한 곳으로 좁혀지지 않았을 때
- 위치정보 이용 동의가 없거나 등록 좌표가 없을 때
