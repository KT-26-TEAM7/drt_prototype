# 클라우드 배포 + ClawOps 실시간 통화 연동

## 0. 무엇을, 왜

지금까지 이 프로젝트는 개발자 PC에서만 로컬로 돌아갔다. 실제 전화(070 번호)를 연결하려면
ClawOps(한국 전화·AI 음성 플랫폼)가 인터넷 너머에서 우리 서버에 접근할 수 있어야 한다.

ClawOps 대시보드에서 만든 AI 에이전트(GPT Realtime + TTS)는 "외부 도구 연결"에
**MCP(Model Context Protocol) 서버 주소**를 등록하는 방식으로 우리 시스템을 호출한다.
그래서 두 가지를 한다.

1. `main_server`·`bridge`·`drt_service`·`mock_drt_server` — 기존 로컬 4종 세트를
   **그대로** [Render](https://render.com)에 배포한다(코드 변경 없음, 인증만 한 겹 추가).
2. `mcp_server/`라는 **얇은 신규 어댑터**를 만들어 배포한다. ClawOps 에이전트가 통화
   중 부르는 도구 3개(`start_call`/`send_utterance`/`end_call`)를 `main_server`의 기존
   `/call/start`·`/call/utterance`·`/call/end`로 그대로 넘긴다 — DRT 판단 로직은
   재구현하지 않는다.

```
전화 (어르신 → ClawOps 070 번호)
   ↓ ClawOps 에이전트 (GPT Realtime + TTS, 대시보드에서 설정한 "다솜이" 페르소나)
   ↓ MCP 도구 호출 (start_call → send_utterance × N → end_call)
mcp_server            (Render, 신규)
   ↓ HTTP + X-Call-Token
main_server            (Render) — 대화 상태·DRT 판단의 유일한 두뇌, 기존 코드 그대로
   ↓ bridge/ + care_call_bot/drt_analyzer.py (in-process import, 기존 그대로)
   ↓ HTTP + X-Relay-Token
drt_service             (Render) — 목적지 검색·경로·예약
   ↓ HTTP
mock_drt_server          (Render) — 배차·차량 위치·조회 링크
```

**핵심 설계 원칙**: `mcp_server`는 상태를 갖지 않는다. `session_id`는 `main_server`가
만들고, ClawOps 에이전트가 통화 내내 자기 대화 문맥에 기억해서 매 도구 호출에 그대로
넘긴다. `mcp_server`가 "마지막 세션"을 임의로 기억해 두는 fallback은 절대 두지 않는다 —
한 프로세스가 여러 통화를 동시에 처리하므로, 그런 fallback은 다른 통화의 세션과
뒤섞이는 사고로 이어질 수 있다.

---

## 1. `mcp_server/` 설계

```
mcp_server/
├─ server.py          # FastMCP 인스턴스 + 도구 3개 + ASGI 앱 조립
├─ requirements.txt    # fastmcp, httpx, uvicorn
├─ Dockerfile
├─ .env.example
└─ .gitignore
```

`bridge/`·`care_call_bot/`를 import하지 않는다 — `main_server`를 HTTP로만 호출하는
완전히 독립된 패키지다.

### SDK: `fastmcp` (공식 `mcp` SDK의 `FastMCP`가 아니라)

공식 `mcp` SDK에 번들된 `FastMCP`는 유지보수 모드로 들어갔고(2026-06-30 v2 베타에서
클래스명이 `MCPServer`로 바뀜), 독립 프로젝트 `fastmcp`(PrefectHQ, v3.x)가 현재
커뮤니티 표준이자 Render 공식 가이드가 쓰는 선택지다. 실제 `pip install fastmcp`로
확인한 버전은 3.4.6.

### 도구 3개

- **`start_call(user_id)`** — 통화당 한 번, 맨 처음에만. `main_server`의 `/call/start`를
  불러 `session_id`와 인사말(`reply`)을 받는다.
- **`send_utterance(session_id, text)`** — 어르신이 한 마디 할 때마다. `/call/utterance`를
  불러 다음에 할 말을 받는다.
- **`end_call(session_id)`** — 통화 종료 시. `/call/end`를 부른다.
  `main_server`의 `/call/end`는 JSON 바디를 받으면 `text` 필드가 필수인
  `UtteranceRequest`로 검증하려 하므로, **`session_id`는 쿼리 파라미터로 보낸다**
  (바디 없이).

모든 도구는 `main_server`가 응답하지 않아도(타임아웃, 연결 불가, 404) 항상 소리 내어
말할 수 있는 `reply`를 반환한다(고정 사과 문구). 예외를 도구 안에서 잡아 항상 말할
문장을 돌려주는 게 의도된 설계다 — 그래야 ClawOps 에이전트가 "reply를 그대로 말하라"는
규칙을 예외 상황에서도 그대로 따를 수 있다.

### ASGI 조립 시 주의할 점 (실제로 겪은 함정)

`mcp.http_app(path="/mcp", stateless_http=True)`가 돌려주는 앱을 `/healthz` 같은
커스텀 라우트와 함께 쓰려면, 부모 `Starlette` 앱 생성자에 **반드시**
`lifespan=mcp_app.lifespan`을 넘겨야 한다. 안 넘기면 첫 MCP 요청마다
`RuntimeError: FastMCP's StreamableHTTPSessionManager task group was not initialized`가
난다(로컬에서 직접 재현·확인함).

```python
app = Starlette(routes=[Route("/healthz", healthz)], lifespan=mcp_app.lifespan)
app.mount("/", mcp_app)
```

### 로컬 실행

```powershell
cd mcp_server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MAIN_SERVER_BASE_URL = "http://127.0.0.1:8002"
.\.venv\Scripts\python.exe server.py
```

`http://127.0.0.1:8080/healthz`가 `ok`를 돌려주면 뜬 것이다.

---

## 2. `main_server` 인증 (`MAIN_SERVER_TOKEN` / `X-Call-Token`)

인터넷에 공개되므로 아무나 `/call/*`를 호출해 예약·문자·Gemini 호출을 유발할 수 있게
두면 안 된다. `drt_service`의 `RELAY_API_TOKEN` 패턴(`APIKeyHeader(auto_error=False)` +
"토큰이 비어 있으면 검사 생략")을 그대로 따랐다 — 단, 별도 이름의 새 토큰을 쓴다
(`RELAY_API_TOKEN`은 bridge↔drt_service 전용이라 재사용하면 신뢰 경계가 섞인다).

`/call/start`·`/call/utterance`·`/call/end`·`/call/{session_id}/state`에 적용된다.
루트(`/`)는 인증 없이 그대로 둔다 — Render 헬스체크와 `scripts/run_stack.py`의 사전
점검이 그걸 쓴다.

**로컬 개발에 영향 없음**: `MAIN_SERVER_TOKEN`을 설정하지 않으면(로컬 `.env` 기본값)
검사 자체를 건너뛴다. 기존 `call_demo.py`, `gemini_chat_demo.py`는 그대로 토큰 없이
동작한다. 아래처럼 직접 확인했다:

| 상황 | 결과 |
|---|---|
| `MAIN_SERVER_TOKEN` 미설정, 토큰 없이 호출 | 200 (통과) |
| `MAIN_SERVER_TOKEN` 미설정, 아무 토큰이나 넣고 호출 | 200 (통과) |
| `MAIN_SERVER_TOKEN` 설정, 토큰 없이 호출 | 401 |
| `MAIN_SERVER_TOKEN` 설정, 틀린 토큰 | 401 |
| `MAIN_SERVER_TOKEN` 설정, 맞는 토큰 | 200 |
| `MAIN_SERVER_TOKEN` 설정, `GET /` (인증 대상 아님) | 200 |

`mcp_server`는 이 토큰 값을 `X-Call-Token` 헤더로 매 호출에 실어 보낸다
(`mcp_server/.env`의 `MAIN_SERVER_TOKEN`을 `main_server`와 같은 값으로 맞추면 된다).

---

## 3. Dockerfile 4개 + 로컬 빌드 검증

베이스 이미지는 전부 `python:3.13-slim`(로컬 `.venv`와 버전 일치).

| 서비스 | Dockerfile | 빌드 컨텍스트 |
|---|---|---|
| `mock_drt_server` | `mock_drt_server/Dockerfile` | `mock_drt_server/` |
| `drt_service` | `drt_service/Dockerfile` | `drt_service/` |
| `main_server` | `main_server/Dockerfile` | **repo root**(`.`) — `bridge/`·`care_call_bot/`를 import하므로 |
| `mcp_server` | `mcp_server/Dockerfile` | `mcp_server/` |

`main_server`의 Dockerfile은 `COPY . .`가 아니라 `bridge/`·`care_call_bot/`·
`main_server/`·`data/`만 선택적으로 복사한다 — repo root에는 다른 세 서비스와 각자의
`.venv/`, sqlite 파일들이 같이 있어서 통째로 복사하면 이미지가 불필요하게 커진다.
`care_call_bot/.env`, `data/*.jsonl`은 `.gitignore`에 있어 Render가 클론하는 git
스냅샷에는 애초에 없으므로 유출 위험은 없다. `GEMINI_KEY`는 `.env` 파일 없이도 Render
환경변수로 넣으면 정상 동작한다(`load_dotenv`가 파일이 없으면 조용히 넘어가고
`os.getenv`는 실제 프로세스 환경변수를 그대로 읽는다).

`drt_service`와 `main_server`는 `PORT` 환경변수를 자기 코드로 읽지 않으므로(둘 다
`mock_drt_server`와 달리 그런 로직이 없다), Dockerfile의 `CMD`가 셸 형태
(`["sh", "-c", "... --port ${PORT:-8001}"]`)로 직접 확장해 준다.

로컬에 Docker가 있다면 Render에 올리기 전에 미리 빌드해 본다:

```powershell
docker build -t mock-drt-server ./mock_drt_server
docker build -t drt-service ./drt_service
docker build -t main-server -f ./main_server/Dockerfile .
docker build -t mcp-server ./mcp_server
```

> 이 리포지토리 작업 환경에는 Docker가 설치돼 있지 않아 이 빌드들은 실제로 실행해
> 보지 못했습니다. Dockerfile 자체(경로, `CMD`, 의존성 설치 순서)는 검토했지만, 실제
> `docker build`는 Docker가 있는 환경에서 한 번 확인해 보시는 걸 권장합니다.

---

## 4. `render.yaml` 사용법

repo root의 `render.yaml`이 4개 서비스를 한 번에 정의한다. Render 대시보드에서
**New + → Blueprint**로 이 저장소를 연결하면 자동으로 읽는다.

### 채워야 하는 값 (`sync: false`로 표시된 것들 — Render 대시보드에서 서비스별로 직접 입력)

| 서비스 | 변수 | 값 |
|---|---|---|
| `mock-drt-server` | `TMAP_APP_KEY` | TMAP 키(비워도 됨 — 모의 장소로 동작) |
| `drt-service` | `RELAY_API_TOKEN` | `secrets.token_urlsafe(32)`로 생성 — **`main-server`와 동일한 값** |
| `drt-service` | `TMAP_APP_KEY` | 위와 같은 키 |
| `main-server` | `RELAY_API_TOKEN` | `drt-service`와 동일한 값 |
| `main-server` | `MAIN_SERVER_TOKEN` | 새로 생성 — **`mcp-server`와 동일한 값** |
| `main-server` | `GEMINI_KEY` | Gemini API 키 |
| `mcp-server` | `MAIN_SERVER_TOKEN` | `main-server`와 동일한 값 |

나머지(서비스 간 URL 등)는 `render.yaml`에 이미 고정값으로 들어 있다 — 서비스
이름(`name:`)이 `https://<이름>.onrender.com`을 그대로 결정하므로, `fromService`
참조 대신 직접 고정값을 썼다.

### SQLite는 당분간 영구 디스크 없이(ephemeral) 간다

Render 무료 티어는 영구 디스크를 붙일 수 없고, 무료 서비스는 재배포·재시작·유휴
스핀다운마다 파일시스템이 초기화된다. `drt_service`(스키마 매 기동 자동 생성)와
`mock_drt_server`(Dockerfile `CMD`에서 매 기동마다 마이그레이션 실행)는 이미
"매번 새로 만들어도 되는" 경로가 있으므로, 지금 단계에서는 이걸 그대로 받아들인다.
실사용 데이터가 아니라 테스트/데모용 목 데이터이기 때문이다. 나중에 실사용 단계가
되면 `render.yaml`에 `disk:` 블록을 추가하고 유료 플랜으로 전환하면 된다.

### ⚠ 콜드 스타트 — 라이브 전화 데모에 직접 영향

Render 무료 웹 서비스는 **15분 무통신 시 스핀다운**되고, 다음 요청에서 **약 1분간
콜드 스타트**한다. 실제 전화가 걸려왔는데 `main-server`나 `mcp-server`가 잠들어
있었다면, 통화 시작 인사나 첫 응답이 최대 1분 멈춘다 — 라이브 데모에는 치명적이다.

**`main-server`와 `mcp-server`는 실제 데모 전에 최소 유료 Starter(상시 구동) 플랜으로
올리는 걸 권장한다** — 이 둘이 통화의 실시간 경로에 직접 있다. `drt-service`·
`mock-drt-server`는 한 단계 뒤에 있어 무료로 좀 더 버틸 수 있지만, 데모 직전에는
넷 다 한 번씩 요청을 보내 미리 깨워 두는 걸 권장한다.

---

## 5. 배포 순서

문제가 생겼을 때 어느 층에서 났는지 바로 알 수 있도록, ClawOps 쪽 미확인 사항을
가장 나중으로 미루도록 순서를 짠다.

1. **`mock-drt-server`만 배포**하고 확인:
   ```powershell
   curl https://mock-drt-server.onrender.com/vehicles
   ```
2. **`drt-service`를 배포**하고, `DRT_SERVER_BASE_URL`로 방금 올린 `mock-drt-server`를
   실제 인터넷 너머로 호출할 수 있는지 확인 — "서비스끼리 인터넷으로 서로 닿는다"는
   전체 계획의 전제를 여기서 처음 검증한다.
3. **`main-server`를 배포**하고, 로컬에 있는 스크립트를 그대로 클라우드 대상으로
   돌려 본다:
   ```powershell
   py scripts\call_demo.py --server https://main-server.onrender.com
   ```
   (단, `MAIN_SERVER_TOKEN`을 설정했다면 `call_demo.py`는 토큰 헤더를 안 보내므로
   401이 납니다 — 이 스크립트는 토큰 없이 확인하고 싶을 때만 쓰고, 인증까지
   포함한 확인은 `mcp_server`가 실제로 붙었을 때 자연스럽게 됩니다.)
4. **그다음에만 `mcp_server`를 배포**한다. 배포된 `main-server`를 가리키게 하고,
   `fastmcp`의 `Client`로 직접 확인:
   ```python
   from fastmcp import Client
   async with Client("https://mcp-server.onrender.com/mcp") as client:
       r = await client.call_tool("start_call", {"user_id": "elder_demo_01"})
       print(r.data)
   ```
5. **그다음에만 ClawOps "외부 도구 연결" 폼을 열어** 정확한 전송 방식/URL 형식을
   "연결 테스트" 버튼으로 확인한다 — MCP URL은 `https://mcp-server.onrender.com/mcp`.
6. **연결이 성공한 뒤에만** 6절의 시스템 프롬프트 추가분을 채워 넣고 실제 테스트 통화.
7. 콜드 스타트가 체감됐다면 그때 유료 플랜 전환을 결정한다.

---

## 6. ClawOps 연동

### "외부 도구 연결"에 등록할 값

- **MCP 서버 주소**: `https://mcp-server.onrender.com/mcp`
- ClawOps가 인증 헤더를 지원하는 형식을 요구하면, `mcp_server` 자체를 잠글지는
  추가로 검토가 필요하다(현재는 잠그지 않음 — `mcp_server`가 할 수 있는 일은 어차피
  `main_server`가 토큰으로 보호하는 3가지 통화 동작뿐이라 데모 단계에서는 위험이
  제한적이라고 판단했다).

### 시스템 프롬프트 추가분

기존에 입력해 둔 페르소나 텍스트 뒤에 이어 붙인다(연결 확인 후에):

```
[도구 사용 규칙 — 반드시 지켜라]

너는 통화 중 아래 세 도구를 이 순서로 사용한다: start_call, send_utterance, end_call.

1. 통화가 연결되면, 어르신이 아무 말도 하기 전에 가장 먼저 start_call을 딱 한 번 호출한다.
   돌려받은 session_id를 통화가 끝날 때까지 기억해 둔다(매번 다시 만들지 않는다).
   돌려받은 reply를 인사말로 그대로, 한 글자도 바꾸지 말고 소리 내어 말한다.

2. 어르신이 한 마디 말할 때마다 send_utterance를 호출한다. session_id는 항상 1번에서
   받은 값을 그대로 넘긴다. text에는 어르신이 방금 하신 말씀을 그대로 넣는다.

3. send_utterance가 돌려준 reply를 반드시 그대로 소리 내어 말한다. 요약하거나 바꾸거나
   덧붙이지 않는다. 이 reply는 미리 정해진 말투(다솜이)와 배차 안내 문구다.

4. call_ended가 true로 오면, 그 reply를 말한 직후 end_call을 호출하고 통화를 마무리한다.

5. 어르신이 먼저 끊으려 하시면 붙잡지 말고 send_utterance를 호출해 그 말씀을 그대로
   전달한다 — 종료 여부는 네가 아니라 메인 서버가 판단한다.

6. 도구 결과에 error나 ok:false가 있어도 당황하지 말고 돌려받은 reply를 그대로 말한다
   (이미 오류 대비 안내 문장이 들어 있다). 같은 도구를 반복 호출하지 않는다.
```

**확인 필요**: ClawOps 실시간 에이전트가 매 발화마다 도구를 부르는지, 아니면 "의도가
감지될 때만" 부르는지 — 후자라면 이 설계(모든 턴이 send_utterance를 거쳐야 함)가
깨진다. 5절에서 실제 통화로 반드시 같이 확인한다.

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `mcp_server` 첫 요청마다 `Task group is not initialized` | `Starlette` 부모 앱에 `lifespan=mcp_app.lifespan`을 안 넘김 | `mcp_server/server.py`의 앱 조립부 확인 |
| `main-server`/`drt-service` 401 | 토큰이 서로 안 맞음 | Render 대시보드에서 `RELAY_API_TOKEN`(drt-service↔main-server), `MAIN_SERVER_TOKEN`(main-server↔mcp-server) 값이 양쪽 서비스에서 정확히 같은지 확인 |
| `send_utterance`가 계속 `session_not_found`(404) | `main-server`가 재배포·재시작돼 인메모리 세션이 날아감(`ConversationStore`가 프로세스 메모리에만 있음), 또는 콜드 스타트 중 다른 인스턴스로 라우팅됨 | 통화 중 재배포하지 않기. 무료 플랜의 여러 인스턴스 분산이 의심되면 유료 플랜에서 인스턴스 수 확인 |
| 통화 시작 인사가 몇십 초 늦게 나옴 | 콜드 스타트(4절) | `main-server`/`mcp-server`를 Starter로 올리거나, 데모 직전에 미리 요청 한 번씩 보내 깨워 둠 |
| `docker build` 안 해봄 | 이 문서를 쓴 환경에 Docker가 없었음(3절 참고) | 실제 빌드 가능한 환경에서 한 번 확인 |
