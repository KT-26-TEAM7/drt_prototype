"""메인 서버 — 통화를 소유하고 대화 상태·의도 분석·DRT 예약을 지휘한다.

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 진입점. 한 턴에 누가 말할지 결정한다 |
| `conversation.py` | 대화 상태 기계. 누적 텍스트 재분석 결함을 여기서 푼다 |
| `analyzer.py` | 케어콜 분석기 어댑터(최신 한 마디만 분석) |
| `talk.py` | 다솜이 안부 대화 응답 |
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
