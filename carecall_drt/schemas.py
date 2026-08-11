"""통합 모듈의 데이터 구조."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SemanticFrame:
    visit_intent: bool = False
    outing_status: str = "unknown"  # unknown | intended | not_needed | refused
    reservation_request: bool = False
    reservation_consent: str = "not_confirmed"  # not_confirmed | confirmed | refused
    destination_category: str = "unknown"
    destination_candidates: list[str] = field(default_factory=list)
    specific_place: str = ""
    place_preference: str = "unknown"  # unknown | nearby | frequent | exact
    mobility_difficulty: bool = False
    emergency_risk: bool = False
    extracted_keywords: list[str] = field(default_factory=list)


@dataclass
class DRTAnalysis:
    dialogue_stage: str
    drt_status: str
    destination_category: str
    destination_candidates: list[str]
    visit_intent: bool
    outing_status: str
    reservation_consent: str
    mobility_difficulty: bool
    emergency_risk: bool
    should_call_gemini: bool
    gemini_used: bool
    specific_place: str
    place_preference: str
    missing_slots: list[str]
    target_slot: str | None
    next_question: str
    reason: str
    extracted_keywords: list[str]
    date: str | None = None
    time: str | None = None
    pickup_location: str | None = None
    ready_for_plan: bool = False
    ready_for_reservation: bool = False
    route_query: str | None = None
    is_specific: bool = False
    rule_latency_ms: float = 0.0
    gemini_latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Location:
    latitude: float
    longitude: float
    accuracy: float | None = None
    captured_at: str | None = None


@dataclass
class SessionState:
    """여러 대화 턴에서 수집한 DRT 슬롯을 유지한다."""

    session_id: str = "default"
    destination_category: str = "unknown"
    destination_candidates: list[str] = field(default_factory=list)
    specific_place: str = ""
    place_preference: str = "unknown"
    visit_intent: bool = False
    outing_status: str = "unknown"
    reservation_consent: str = "not_confirmed"
    mobility_difficulty: bool = False
    emergency_risk: bool = False
    date: str | None = None
    time: str | None = None
    pickup_location: str | None = None
    location: Location | None = None
    last_target_slot: str | None = None
    last_analysis: DRTAnalysis | None = None
    pending_plan: dict[str, Any] | None = None
    pending_reservation: dict[str, Any] | None = None
    pending_plan_request: dict[str, Any] | None = None

    def reset_drt(self) -> None:
        session_id = self.session_id
        location = self.location
        self.__dict__.update(SessionState(session_id=session_id, location=location).__dict__)


@dataclass
class JointLLMResult:
    assistant_reply: str = ""
    semantic: dict[str, Any] | None = None
    end_call: bool = False
    latency_ms: float | None = None
    # Gemini joint 호출을 이미 시도했다면 같은 턴에 의미 분석 API를 재호출하지 않는다.
    semantic_call_attempted: bool = False


@dataclass
class TurnResult:
    assistant_reply: str
    analysis: DRTAnalysis
    plan: dict[str, Any] | None = None
    backend_error: str | None = None
    end_call: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_reply": self.assistant_reply,
            "analysis": self.analysis.to_dict(),
            "plan": self.plan,
            "backend_error": self.backend_error,
            "end_call": self.end_call,
        }
