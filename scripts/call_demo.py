"""메인 서버에 통화를 걸어 대화를 흘려 보는 시연 도구.

전화망 대신 터미널로 말을 걸어, 메인 서버가 대화 상태를 어떻게 이어 가는지
확인한다. 표준 라이브러리만 쓴다.

    py scripts/call_demo.py                    # 미리 짜 둔 시나리오 실행
    py scripts/call_demo.py --interactive      # 직접 입력하며 대화
    py scripts/call_demo.py --scenario revoke  # 번복 시나리오만
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://127.0.0.1:8002"

# 예전 구조에서 막히던 흐름이다. "집에 있을래" 뒤에 마음을 바꾸셔도 예약이 되어야 한다.
SCENARIOS: dict[str, list[str]] = {
    # TMAP이 MOCK일 때 모의 장소가 정형외과 계열뿐이라, 끝까지 가는 시연은 그쪽으로 맞췄다.
    # 실제 TMAP 키를 넣으면 치과·시장 등 어떤 목적지로도 같은 흐름이 돈다.
    "revoke": [
        "요즘 무릎이 좀 아파서 정형외과에 가야 하나 싶어.",
        "아니다, 오늘은 그냥 집에 있을래.",
        "그래도 무릎이 계속 아프네. 역시 정형외과에 가야겠어.",
        "응, 차 좀 불러줘.",
        "가까운 정형외과로 해줘.",
        "응 불러줘",
    ],
    # carecall_drt는 즉시 배차 전에 날짜·시간·픽업위치까지 슬롯으로 확인한다
    # (drt_service 자체는 여전히 이 값들을 받지 않는 즉시 호출 모델이지만, 대화
    # 흐름은 다 여쭤본 뒤에 계획을 세운다 — docs/04_carecall_drt_이식.md 참고).
    "basic": [
        "남현서울정형외과에 가야 하는데 차 좀 불러줘.",
        "응 불러줘",
        "오늘",
        "오전 열시",
        "집 앞에서 탈게",
        "서울정형외과의원으로 해줘",
        "응 불러줘",
    ],
    "emergency": [
        "방금 넘어졌는데 못 일어나겠어. 움직일 수가 없어.",
        "그래도 병원은 가야 하는데 차 좀 불러줘.",
    ],
    "chat": [
        "그냥 그렇지 뭐.",
        "어제는 잠을 잘 못 잤어.",
    ],
}


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"요청 실패({error.code}): {body[:200]}")
    except urllib.error.URLError as error:
        raise SystemExit(
            f"메인 서버에 붙지 못했습니다: {url}\n  {error.reason}\n"
            "  py scripts/run_stack.py 로 먼저 띄우세요."
        )


def show(reply: dict) -> None:
    who = {"dasom": "다솜이", "drt": "다솜이(안내)", "system": "시스템"}.get(
        reply.get("speaker", ""), "다솜이"
    )
    print(f"  {who} : {reply['reply']}")
    state = reply.get("state") or {}
    details = [f"단계={state.get('dialogue_stage')}"]
    if state.get("destination_category") and state["destination_category"] != "unknown":
        details.append(f"목적지={state['destination_category']}")
    if reply.get("expects"):
        details.append(f"기다림={reply['expects']}")
    if reply.get("drt_action"):
        details.append(f"drt={reply['drt_action']}")
    if reply.get("sms_sent"):
        details.append(f"문자={','.join(reply['sms_sent'])}")
    print(f"         [{' · '.join(details)}]")
    if reply.get("tracking_url"):
        print(f"         조회 링크: {reply['tracking_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="메인 서버 통화 시연")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--user", default="elder_demo_01")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="한 시나리오만 실행")
    parser.add_argument("--interactive", action="store_true", help="직접 입력하며 대화")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    root = json.loads(urllib.request.urlopen(f"{args.server}/", timeout=10).read())
    print(f"메인 서버: 응답기={root.get('responder')} / DRT 백엔드={root.get('drt_backend_enabled')}")

    scenarios = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS
    if args.interactive:
        scenarios = {"직접 입력": []}

    for name, utterances in scenarios.items():
        print()
        print("=" * 70)
        print(f"[{name}]")
        print("=" * 70)
        started = post(f"{args.server}/call/start", {"user_id": args.user})
        session_id = started["session_id"]
        print(f"  다솜이 : {started['reply']}")

        if args.interactive:
            while True:
                try:
                    text = input("  어르신 : ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not text or text in ("종료", "끝", "quit"):
                    break
                show(post(f"{args.server}/call/utterance",
                          {"session_id": session_id, "text": text}))
        else:
            for text in utterances:
                print(f"\n  어르신 : {text}")
                reply = post(f"{args.server}/call/utterance",
                             {"session_id": session_id, "text": text})
                show(reply)
                if reply.get("call_ended"):
                    break

        post(f"{args.server}/call/end", {"session_id": session_id, "text": "종료"})

    print()


if __name__ == "__main__":
    main()
