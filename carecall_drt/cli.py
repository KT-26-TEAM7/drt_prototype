"""공통 CLI 대화 루프."""

from __future__ import annotations

import json
from typing import Any

from .orchestrator import CareCallDRTOrchestrator
from .responses import GREETING
from .schemas import Location, SessionState
from .voice import detect_tts, listen, load_stt, speak


def _consent(voice: bool, stt: Any | None) -> bool:
    question = "통화 내용과 인공지능 분석을 이용해 안부와 이동 요청을 도와드려도 될까요?"
    print(f"다솜이: {question}")
    if voice:
        answer = listen(stt)
        print(f"어르신: {answer}")
    else:
        answer = input("어르신(네/아니오): ").strip()
    compact = answer.replace(" ", "")
    return compact.startswith(("네", "예", "응", "그래"))


def run_chat(
    orchestrator: CareCallDRTOrchestrator,
    *,
    voice: bool = False,
    stt_model: str = "small",
    no_tts: bool = False,
    skip_consent: bool = False,
    show_json: bool = True,
    location: Location | None = None,
) -> None:
    stt = load_stt(stt_model) if voice else None
    tts_engine = None if no_tts else detect_tts()
    if not skip_consent and not _consent(voice, stt):
        farewell = "알겠습니다, 어르신. 동의하지 않으셔서 통화를 종료할게요. 건강히 지내세요."
        print(f"다솜이: {farewell}")
        speak(farewell, tts_engine)
        return

    state = SessionState(session_id="cli", location=location)
    history: list[dict[str, str]] = [{"role": "assistant", "content": GREETING}]
    print(f"다솜이: {GREETING}")
    speak(GREETING, tts_engine)

    while True:
        try:
            if voice:
                user_text = listen(stt)
                if not user_text:
                    print("(잘 못 들었어요. 다시 한번 말씀해 주세요.)")
                    continue
                print(f"어르신: {user_text}")
            else:
                user_text = input("어르신: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n대화를 마칩니다.")
            break

        if not user_text:
            continue
        if user_text.lower() in {"종료", "끝", "quit", "exit"}:
            farewell = "오늘 이야기 나눠서 즐거웠어요. 또 전화드릴게요. 건강히 지내세요."
            print(f"다솜이: {farewell}")
            speak(farewell, tts_engine)
            break

        result = orchestrator.process_turn(user_text, state, history)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": result.assistant_reply})
        print(f"다솜이: {result.assistant_reply}")
        speak(result.assistant_reply, tts_engine)

        if show_json:
            compact = {
                "dialogue_stage": result.analysis.dialogue_stage,
                "drt_status": result.analysis.drt_status,
                "destination_category": result.analysis.destination_category,
                "specific_place": result.analysis.specific_place,
                "place_preference": result.analysis.place_preference,
                "missing_slots": result.analysis.missing_slots,
                "target_slot": result.analysis.target_slot,
                "route_query": result.analysis.route_query,
                "ready_for_reservation": result.analysis.ready_for_reservation,
                "gemini_used": result.analysis.gemini_used,
                "plan": result.plan,
                "backend_error": result.backend_error,
            }
            print("[DRT 분석]", json.dumps(compact, ensure_ascii=False, default=str))

        if result.end_call:
            print("(통화를 마칩니다.)")
            break
