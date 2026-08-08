"""케어콜 대화 분석 결과를 DRT 예약 서비스로 넘기는 브릿지.

care-call-bot(케어콜 대화·의도 분석)과 drt_service(정류장·경로·예약 API)는
서로 다른 리포이고 서로를 import하지 않는다. 이 패키지는 그 사이에서
"분석 결과 JSON -> DRT API 요청 -> 음성으로 읽을 응답"을 담당한다.

진입점은 `bridge.orchestrator.DrtHandoff`이다.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
