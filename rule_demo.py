"""API 키/대형 모델 없이 다중 턴 통합 흐름을 확인하는 예제."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.cli import run_chat
from carecall_drt.config import Settings
from carecall_drt.orchestrator import CareCallDRTOrchestrator
from carecall_drt.responses import RuleCareResponder
from carecall_drt.schemas import Location


def main() -> None:
    settings = Settings(gemini_policy="off")
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(settings),
        responder=RuleCareResponder(),
    )
    location = None
    if settings.demo_latitude is not None and settings.demo_longitude is not None:
        location = Location(settings.demo_latitude, settings.demo_longitude, settings.demo_accuracy)
    run_chat(orchestrator, skip_consent=True, show_json=True, location=location)


if __name__ == "__main__":
    main()
