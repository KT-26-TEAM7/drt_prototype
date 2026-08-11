from __future__ import annotations

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.config import Settings
from carecall_drt.schemas import Location, SessionState


def test_multiturn_slot_collection_to_ready() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState(location=Location(37.4849, 126.9710, 15))
    sequence = [
        ("병원 가고 싶어", "reservation_consent"),
        ("무릎이 아파", "reservation_consent"),
        ("네", "place_resolution_method"),
        ("가까운 곳", "date"),
        ("내일", "time"),
        ("오전 10시", "pickup_location"),
        ("집 앞", None),
    ]
    result = None
    for utterance, expected_target in sequence:
        result = analyzer.analyze_turn(utterance, state, allow_internal_gemini=False)
        assert result.target_slot == expected_target
    assert result is not None
    assert result.destination_category == "medical_orthopedics"
    assert result.reservation_consent == "confirmed"
    assert result.place_preference == "nearby"
    assert result.date == "내일"
    assert result.time == "오전 10시"
    assert result.pickup_location == "집 앞"
    assert result.route_query == "정형외과"
    assert result.ready_for_plan is True
    assert result.ready_for_reservation is True


def test_specific_place_requires_no_place_resolution() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState(location=Location(37.4849, 126.9710, 15))
    result = analyzer.analyze_turn(
        "중앙약국까지 오늘 오후 3시에 집 앞에서 차 좀 불러줘",
        state,
        allow_internal_gemini=False,
    )
    assert result.specific_place == "중앙약국"
    assert result.is_specific is True
    assert "place_resolution_method" not in result.missing_slots
    assert result.ready_for_reservation is True


def test_social_visit_requires_exact_destination() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState()
    result = analyzer.analyze_turn("손자 집에 가야 하는데 차 좀 불러줘", state, allow_internal_gemini=False)
    assert result.destination_category == "social_family_visit"
    assert result.target_slot == "exact_destination"
    follow = analyzer.analyze_turn("서울 동작구 사당로 10", state, allow_internal_gemini=False)
    assert follow.specific_place == "서울 동작구 사당로 10"


def test_negative_confirmation_stops_drt() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState()
    first = analyzer.analyze_turn("가까운 약국에 가고 싶어", state, allow_internal_gemini=False)
    assert first.target_slot == "reservation_consent"
    second = analyzer.analyze_turn("아니요", state, allow_internal_gemini=False)
    assert second.dialogue_stage == "not_needed"
    assert second.reservation_consent == "refused"
