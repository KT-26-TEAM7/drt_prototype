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


def test_pickup_location_accepts_free_text_place_name() -> None:
    """실제 통화(2026-08-12)에서 재현된 버그: "출발하실 위치를 알려주실 수
    있을까요?"에 "사당역"이라고 답해도 extract_pickup()이 "집 앞"류 고정 문구만
    인식해 같은 질문을 무한 반복했다. exact_destination과 같은 방식으로, 방금
    그 슬롯을 물어본 경우에는 원문을 그대로 픽업 위치로 받아야 한다."""
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState(location=Location(37.4849, 126.9710, 15))
    sequence = [
        ("병원 가고 싶어", "reservation_consent"),
        ("무릎이 아파", "reservation_consent"),
        ("네", "place_resolution_method"),
        ("가까운 곳", "date"),
        ("내일", "time"),
        ("오전 10시", "pickup_location"),
    ]
    for utterance, expected_target in sequence:
        result = analyzer.analyze_turn(utterance, state, allow_internal_gemini=False)
        assert result.target_slot == expected_target

    first_reply = analyzer.analyze_turn("사당역", state, allow_internal_gemini=False)
    assert first_reply.pickup_location == "사당역"
    assert "pickup_location" not in first_reply.missing_slots
    assert first_reply.target_slot != "pickup_location"

    # 같은 슬롯을 두 번 물어도 루프에 빠지지 않는지 — 이미 채워졌으므로 다시
    # 물으면 안 된다.
    assert state.pickup_location == "사당역"


def test_is_affirmative_recognizes_bulleojwo() -> None:
    """실제 통화(2026-08-12)에서 재현된 버그: 경로 확인 질문("이 경로로
    예약할까요?")에 "어 불러줘"/"불러줘"라고 반복 답해도 인식하지 못해 같은
    질문만 되풀이됐다. "불러줘"는 애초에 차량을 요청할 때 쓰는 동사와 같은데도
    확인 답변으로는 감지되지 않고 있었다. 부정형("안 불러도 돼")과는 구분돼야
    한다."""
    from carecall_drt.analyzer import is_affirmative, is_negative

    assert is_affirmative("어 불러줘") is True
    assert is_affirmative("응 불러줘") is True
    assert is_affirmative("불러줘") is True
    assert is_affirmative("안 불러도 돼") is False
    assert is_negative("아니 안 불러도 돼") is True


def test_negative_confirmation_stops_drt() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState()
    first = analyzer.analyze_turn("가까운 약국에 가고 싶어", state, allow_internal_gemini=False)
    assert first.target_slot == "reservation_consent"
    second = analyzer.analyze_turn("아니요", state, allow_internal_gemini=False)
    assert second.dialogue_stage == "not_needed"
    assert second.reservation_consent == "refused"
