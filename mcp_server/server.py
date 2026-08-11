"""ClawOps(전화 AI 에이전트)가 통화 중 호출하는 MCP 도구 서버.

대화 상태·DRT 판단 로직은 전부 main_server(main_server/app.py)가 가진다. 이 서버는
그걸 재구현하지 않고 그대로 HTTP로 부르는 얇은 어댑터다 — scripts/call_demo.py,
care_call_bot/gemini_chat_demo.py가 이미 하는 일(POST /call/start → /call/utterance
반복 → /call/end)을 MCP 도구 형태로 옮긴 것뿐이다.

**상태를 갖지 않는다.** session_id는 main_server가 만들고 관리하며, 통화를 거는
쪽(ClawOps 에이전트)이 자기 대화 문맥에 기억해서 매 도구 호출에 그대로 넘긴다.
이 서버가 "마지막 세션"을 임의로 기억해 두는 fallback은 절대 두지 않는다 — 한
프로세스가 여러 통화를 동시에 처리하므로, 그런 fallback은 다른 통화의 세션과
뒤섞이는 사고로 이어질 수 있다.

모든 도구는 main_server가 응답하지 않아도(타임아웃·연결 불가) 항상 소리 내어
말할 수 있는 reply를 돌려준다. 호출하는 에이전트에게 "reply를 그대로 말하라"고
지시할 것이므로, 도구가 예외를 던지면 에이전트가 즉흥적으로 뭔가 지어내게 되어
main_server가 공들여 만든 결정론적 응답(상태 기계, 규칙 기반 문장)의 의미가
없어진다 — 그래서 예외를 도구 안에서 잡아 항상 말할 문장을 돌려주는 게 의도된
설계다.

실행:
    python server.py                 # PORT 환경변수(기본 8080)로 기동
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

MAIN_SERVER_BASE_URL = os.environ.get("MAIN_SERVER_BASE_URL", "http://127.0.0.1:8002").rstrip("/")
MAIN_SERVER_TOKEN = os.environ.get("MAIN_SERVER_TOKEN", "").strip()
# Render 무료 플랜은 유휴 시 스핀다운되고 다음 요청에서 최대 ~1분 콜드 스타트한다.
# 기본 타임아웃을 짧게 두면 콜드 스타트 중인 main_server를 "연결 불가"로 오판해
# 실제 통화에서 실패 문구가 나간다(2026-08-11 실제 통화에서 확인). 60초로 늘려
# 콜드 스타트를 기다릴 여유를 준다 — 상시 구동(Starter) 플랜으로 올리면 이 여유가
# 필요 없어지지만, 그 전까지는 이 값이 실패보다는 몇십 초 대기가 낫다는 판단이다.
HTTP_TIMEOUT_S = float(os.environ.get("MAIN_SERVER_TIMEOUT_S", "60"))
FALLBACK_REPLY = "죄송해요, 지금 잠깐 연결이 원활하지 않아요. 잠시 후에 다시 말씀해 주시겠어요?"

mcp = FastMCP("다솜이 DRT 통화 도구")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if MAIN_SERVER_TOKEN:
        headers["X-Call-Token"] = MAIN_SERVER_TOKEN
    return headers


@mcp.tool
def start_call(user_id: str) -> dict:
    """통화를 시작하고 세션을 만든다. 통화당 딱 한 번, 맨 처음에만 호출한다.

    반환된 session_id를 통화가 끝날 때까지 기억해서, 이후 이 통화 동안의 모든
    send_utterance / end_call 호출에 그대로 넘겨야 한다(매번 새로 만들지 않는다).
    반환된 reply는 인사말이다. 한 글자도 바꾸지 말고 그대로 소리 내어 말한다.
    """
    try:
        response = httpx.post(
            f"{MAIN_SERVER_BASE_URL}/call/start",
            json={"user_id": user_id}, headers=_headers(), timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {
            "session_id": "", "reply": FALLBACK_REPLY, "expects": "",
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool
def send_utterance(session_id: str, text: str) -> dict:
    """어르신의 발화 한 마디를 메인 서버로 보내고, 다음에 할 말을 받는다.
    어르신이 뭔가 말할 때마다(의미 있는 발화가 끝날 때마다) 이 도구를 호출한다.

    session_id는 반드시 start_call이 돌려준 값을 그대로 넘긴다(새로 지어내지 않는다).
    반환된 reply를 반드시 그대로, 다른 말로 바꾸거나 요약하지 말고 소리 내어 말한다 —
    다솜이 말투와 DRT 배차 안내 문구는 미리 정해진 고정 문구이며 임의로 바꾸면 안 된다.
    call_ended가 true이면 reply를 말한 다음 end_call을 호출하고 통화를 마친다.
    """
    if not session_id:
        return {
            "reply": "통화가 아직 시작되지 않았어요.", "speaker": "system",
            "call_ended": False, "ok": False, "error": "missing_session_id",
        }
    try:
        response = httpx.post(
            f"{MAIN_SERVER_BASE_URL}/call/utterance",
            json={"session_id": session_id, "text": text},
            headers=_headers(), timeout=HTTP_TIMEOUT_S,
        )
        if response.status_code == 404:
            return {
                "reply": FALLBACK_REPLY, "speaker": "system", "call_ended": False,
                "ok": False, "error": "session_not_found",
            }
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {
            "reply": FALLBACK_REPLY, "speaker": "system", "call_ended": False,
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool
def end_call(session_id: str) -> dict:
    """통화를 종료 처리한다. 어르신이 전화를 끊으려 하거나 send_utterance가
    call_ended=true를 돌려준 직후에 호출한다. reply는 작별 인사이며 그대로 말한다.
    """
    try:
        # session_id는 쿼리 파라미터로 보낸다. main_server의 /call/end는 JSON 바디를
        # 받으면 text 필드가 필수인 UtteranceRequest로 검증하려 하므로, 바디 없이 보낸다.
        response = httpx.post(
            f"{MAIN_SERVER_BASE_URL}/call/end",
            params={"session_id": session_id}, headers=_headers(), timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"ok": False, "reply": "안녕히 계세요.", "error": f"{type(exc).__name__}: {exc}"}


async def healthz(_request):
    return PlainTextResponse("ok")


# stateless_http=True: 서버가 여러 인스턴스로 뜨거나 재시작돼도 MCP 세션 자체에
# 서버 쪽 상태가 없어야 한다(우리 상태는 전부 main_server의 session_id에 있다).
mcp_app = mcp.http_app(path="/mcp", stateless_http=True)

# ClawOps가 streamable-HTTP 대신 다른 경로/전송을 기대할 수 있어, Render 헬스체크용
# /healthz를 같은 앱에 얹어 둔다. mcp_app의 lifespan을 부모 앱에 반드시 넘겨야
# StreamableHTTP 세션 매니저가 초기화된다(넘기지 않으면 매 요청이 RuntimeError).
app = Starlette(routes=[Route("/healthz", healthz)], lifespan=mcp_app.lifespan)
app.mount("/", mcp_app)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
