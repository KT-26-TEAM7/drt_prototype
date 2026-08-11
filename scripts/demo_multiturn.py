"""API 키 없이 예약 슬롯 수집 흐름을 자동 재생한다."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.config import Settings
from carecall_drt.orchestrator import CareCallDRTOrchestrator
from carecall_drt.responses import RuleCareResponder
from carecall_drt.schemas import Location, SessionState


def main() -> None:
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(Settings(gemini_policy="off")),
        responder=RuleCareResponder(),
    )
    state = SessionState(location=Location(37.4849, 126.9710, 15))
    history = []
    turns = ["병원 가고 싶어", "무릎이 아파", "네", "가까운 곳", "내일", "오전 10시", "집 앞"]
    for text in turns:
        result = orchestrator.process_turn(text, state, history)
        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": result.assistant_reply},
            ]
        )
        print(f"\n어르신: {text}")
        print(f"다솜이: {result.assistant_reply}")
        print(
            "DRT:",
            json.dumps(
                {
                    "stage": result.analysis.dialogue_stage,
                    "category": result.analysis.destination_category,
                    "target_slot": result.analysis.target_slot,
                    "missing": result.analysis.missing_slots,
                    "ready_for_reservation": result.analysis.ready_for_reservation,
                },
                ensure_ascii=False,
            ),
        )


if __name__ == "__main__":
    main()
