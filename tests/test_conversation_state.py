"""대화 상태 기계 검증.

가장 중요한 것은 **번복 가능성**이다. 예전 구조에서는 어르신이 한 번이라도
"오늘은 집에 있을래"라고 하시면 그 통화에서 다시는 예약할 수 없었다
(분석기가 누적 텍스트를 매번 다시 해석했기 때문). 상태 기계로 옮기면서
나중 발화가 앞선 발화를 뒤집을 수 있어야 한다.
"""
from __future__ import annotations

import unittest

from main_server.conversation import (
    STAGE_EMERGENCY,
    STAGE_NEED_DETECTION,
    STAGE_NOT_NEEDED,
    STAGE_RESERVATION_CONFIRM,
    STAGE_RESERVATION_INFO,
    ConversationState,
    ConversationStore,
    TurnFacts,
)


def turn(**overrides) -> TurnFacts:
    """분석기가 한 마디를 보고 돌려줄 법한 결과를 만든다."""
    payload = {
        "dialogue_stage": "need_detection",
        "destination_category": "unknown",
        "destination_candidates": [],
        "search_keywords": [],
        "search_mode": "not_applicable",
        "missing_slots": ["visit_intent", "reservation_consent"],
        "reservation_consent": "not_confirmed",
        "guardian_notify_consent": "not_asked",
        "emergency_risk": False,
        "extracted_keywords": [],
        "next_question": "",
    }
    payload.update(overrides)
    return TurnFacts.from_analyzer_output(payload)


def 목적지_발화(category="medical_dental", place="치과", stage="reservation_confirm") -> TurnFacts:
    return turn(
        dialogue_stage=stage,
        destination_category=category,
        destination_candidates=[place],
        search_keywords=[place],
        search_mode="nearby_search",
        missing_slots=["reservation_consent"],
    )


def 예약요청_발화() -> TurnFacts:
    return turn(
        dialogue_stage="reservation_info_collection",
        reservation_consent="confirmed",
        missing_slots=["date", "time", "pickup_location"],
    )


def 거절_발화() -> TurnFacts:
    return turn(dialogue_stage="not_needed", reservation_consent="refused", missing_slots=[])


def state() -> ConversationState:
    return ConversationState(session_id="CALL-TEST", user_id="elder_demo_01")


class 번복가능성테스트(unittest.TestCase):
    """이 클래스가 이번 작업의 핵심 회귀 테스트다."""

    def test_집에_있겠다_하신_뒤에도_다시_예약할_수_있다(self):
        # 예전 결함: "집에 있을래"가 누적 텍스트에 남아 이후 예약 요청을 계속 무력화했다.
        s = state()
        s.apply(목적지_발화())          # "치과 가야 해"
        s.apply(거절_발화())            # "아니 오늘은 집에 있을래"
        self.assertEqual(s.stage, STAGE_NOT_NEEDED)

        s.apply(목적지_발화())          # "역시 치과 가야겠어"
        self.assertNotEqual(s.stage, STAGE_NOT_NEEDED)
        self.assertEqual(s.stage, STAGE_RESERVATION_CONFIRM)

        s.apply(예약요청_발화())        # "차 좀 불러줘"
        self.assertEqual(s.stage, STAGE_RESERVATION_INFO)
        self.assertEqual(s.reservation_consent, "confirmed")

    def test_예약요청만으로도_앞선_거절이_풀린다(self):
        s = state()
        s.apply(목적지_발화())
        s.apply(거절_발화())
        s.apply(예약요청_발화())  # 목적지를 다시 말하지 않아도
        self.assertEqual(s.stage, STAGE_RESERVATION_INFO)
        self.assertFalse(s.outing_refused)

    def test_거절하면_목적지도_함께_비운다(self):
        # 외출을 접으셨는데 옛 목적지가 남아 있으면 엉뚱한 곳으로 배차될 수 있다.
        s = state()
        s.apply(목적지_발화())
        self.assertTrue(s.destination)
        s.apply(거절_발화())
        self.assertFalse(s.destination)


class 상태이어가기테스트(unittest.TestCase):
    def test_목적지를_다시_말하지_않아도_이어진다(self):
        # "치과 가야 해" -> "응 불러줘" 에서 두 번째 발화만 보면 목적지가 없다.
        s = state()
        s.apply(목적지_발화())
        s.apply(예약요청_발화())
        self.assertEqual(s.destination["destination_category"], "medical_dental")
        self.assertEqual(s.to_analyzer_output()["search_keywords"], ["치과"])

    def test_새_목적지를_말하면_통째로_바뀐다(self):
        s = state()
        s.apply(목적지_발화("medical_dental", "치과"))
        s.apply(목적지_발화("shopping_market", "시장"))
        merged = s.to_analyzer_output()
        self.assertEqual(merged["destination_category"], "shopping_market")
        self.assertEqual(merged["search_keywords"], ["시장"])  # 옛 검색어가 남지 않는다

    def test_한번_채운_날짜시간은_유지된다(self):
        s = state()
        s.apply(목적지_발화())
        s.apply(turn(dialogue_stage="reservation_info_collection",
                     reservation_consent="confirmed",
                     missing_slots=["pickup_location"]))   # 날짜·시간은 채워짐
        s.apply(예약요청_발화())                            # 이번 턴엔 다시 비어 보임
        self.assertIn("date", s.filled_slots)
        self.assertIn("time", s.filled_slots)

    def test_동의_신호가_없는_턴은_이전_동의를_지운다면_안_된다(self):
        s = state()
        s.apply(예약요청_발화())
        self.assertEqual(s.reservation_consent, "confirmed")
        s.apply(turn())  # 신호 없는 잡담
        self.assertEqual(s.reservation_consent, "confirmed")


class 안전테스트(unittest.TestCase):
    def test_응급은_한번_감지되면_유지된다(self):
        # 통화 중 저절로 풀리면 안 된다.
        s = state()
        s.apply(turn(dialogue_stage="emergency", emergency_risk=True))
        self.assertEqual(s.stage, STAGE_EMERGENCY)
        s.apply(목적지_발화())
        self.assertEqual(s.stage, STAGE_EMERGENCY)
        s.apply(예약요청_발화())
        self.assertEqual(s.stage, STAGE_EMERGENCY)

    def test_응급이면_목적지를_브릿지에_넘기지_않는다(self):
        s = state()
        s.apply(목적지_발화())
        s.apply(turn(dialogue_stage="emergency", emergency_risk=True))
        merged = s.to_analyzer_output()
        self.assertEqual(merged["destination_category"], "unknown")
        self.assertTrue(merged["emergency_risk"])

    def test_예약이_끝나면_다시_예약단계로_돌아가지_않는다(self):
        s = state()
        s.apply(목적지_발화())
        s.apply(예약요청_발화())
        s.mark_reserved()
        s.apply(예약요청_발화())  # 또 "불러줘"라고 하셔도
        self.assertEqual(s.stage, "reservation_completed")


class 브릿지계약테스트(unittest.TestCase):
    """상태 기계 출력이 브릿지가 기대하는 모양이어야 한다."""

    def test_브릿지가_그대로_읽을_수_있다(self):
        from bridge.contract import CareCallResult
        from bridge import gate

        s = state()
        s.apply(목적지_발화())
        s.apply(예약요청_발화())
        result = CareCallResult.from_analyzer_output(s.to_analyzer_output())
        self.assertEqual(result.dialogue_stage, STAGE_RESERVATION_INFO)
        self.assertEqual(result.reservation_consent, "confirmed")
        self.assertTrue(gate.evaluate(result).should_call_drt)

    def test_거절_상태는_브릿지가_호출을_막는다(self):
        from bridge.contract import CareCallResult
        from bridge import gate

        s = state()
        s.apply(거절_발화())
        result = CareCallResult.from_analyzer_output(s.to_analyzer_output())
        self.assertFalse(gate.evaluate(result).should_call_drt)

    def test_아직_의향만_있으면_동의를_먼저_묻는다(self):
        from bridge.contract import CareCallResult
        from bridge import gate

        s = state()
        s.apply(목적지_발화())
        result = CareCallResult.from_analyzer_output(s.to_analyzer_output())
        decision = gate.evaluate(result)
        self.assertFalse(decision.should_call_drt)
        self.assertEqual(decision.code, "reservation_consent_pending")

    def test_목적지가_안_정해졌으면_엉뚱한_질문을_넘기지_않는다(self):
        # 분석기의 next_question은 한 마디만 보고 만든 것이라 병합 상태와 어긋날 수 있다.
        # 목적지가 미정인데 "날짜를 알려주세요"를 물으면 대화가 헛돈다.
        s = state()
        s.apply(turn(
            dialogue_stage="reservation_info_collection",
            destination_category="medical_dental",
            destination_candidates=["치과"],
            search_keywords=["치과"],
            search_mode="ask_frequent_or_nearby",
            place_resolution_question="평소 자주 가시는 치과가 있으실까요?",
            missing_slots=["place_resolution_method", "date", "time"],
            reservation_consent="confirmed",
            next_question="가실 날짜와 시간을 알려주실 수 있을까요?",
        ))
        merged = s.to_analyzer_output()
        self.assertIn("place_resolution_method", merged["missing_slots"])
        self.assertEqual(merged["next_question"], "")
        self.assertIn("치과", merged["place_resolution_question"])

    def test_동의를_묻는_단계에서는_분석기_질문을_그대로_쓴다(self):
        # 목적지가 미정이어도, 아직 동의를 묻는 단계라면 "예약을 도와드릴까요?"가 맞다.
        s = state()
        s.apply(turn(
            dialogue_stage="reservation_confirm",
            destination_category="medical_dental",
            destination_candidates=["치과"],
            search_keywords=["치과"],
            search_mode="ask_frequent_or_nearby",
            missing_slots=["place_resolution_method", "reservation_consent"],
            next_question="치과에 가시는 이동 차량 예약을 도와드릴까요?",
        ))
        merged = s.to_analyzer_output()
        self.assertEqual(merged["dialogue_stage"], STAGE_RESERVATION_CONFIRM)
        self.assertIn("예약을 도와드릴까요", merged["next_question"])

    def test_첫_턴은_방문의향부터_확인한다(self):
        s = state()
        s.apply(turn())
        merged = s.to_analyzer_output()
        self.assertEqual(merged["dialogue_stage"], STAGE_NEED_DETECTION)
        self.assertEqual(merged["missing_slots"], ["visit_intent", "reservation_consent"])


class 세션보관소테스트(unittest.TestCase):
    def test_통화별로_상태가_분리된다(self):
        store = ConversationStore()
        a = store.create("CALL-A", "elder_demo_01")
        b = store.create("CALL-B", "elder_demo_02")
        a.apply(목적지_발화())
        self.assertTrue(a.destination)
        self.assertFalse(b.destination)
        self.assertEqual(store.active_count(), 2)
        self.assertTrue(store.end("CALL-A"))
        self.assertIsNone(store.get("CALL-A"))


if __name__ == "__main__":
    unittest.main()
