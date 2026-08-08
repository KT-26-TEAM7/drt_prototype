"""분석 결과 정규화와 DRT 호출 게이트 검증."""
from __future__ import annotations

import unittest

from bridge import gate
from bridge.contract import CareCallResult, recover_specific_place


def _result(**overrides) -> CareCallResult:
    payload = {
        "dialogue_stage": "reservation_info_collection",
        "drt_status": "needed",
        "destination_category": "shopping_market",
        "search_keywords": ["시장"],
        "search_mode": "nearby_search",
        "missing_slots": ["pickup_location"],
        "reservation_consent": "confirmed",
    }
    payload.update(overrides)
    return CareCallResult.from_analyzer_output(payload)


class ContractTest(unittest.TestCase):
    def test_알_수_없는_필드는_무시하고_빠진_필드는_기본값을_쓴다(self):
        # v4.py(구버전 분석기)는 search_mode 같은 키를 아예 내보내지 않는다.
        result = CareCallResult.from_analyzer_output(
            {"dialogue_stage": "need_detection", "미래에_추가된_필드": 123}
        )
        self.assertEqual(result.dialogue_stage, "need_detection")
        self.assertEqual(result.search_mode, "")
        self.assertEqual(result.destination_candidates, [])

    def test_출력에서_사라진_정확명을_키워드에서_복원한다(self):
        # drt_analyzer.py는 specific_place를 OUTPUT_KEYS에 넣지 않는다.
        result = CareCallResult.from_analyzer_output({
            "search_mode": "exact_place",
            "extracted_keywords": ["내일", "오후 1시", "집 앞", "사당솔밭도서관"],
        })
        self.assertEqual(result.specific_place, "사당솔밭도서관")

    def test_일반명사만_있으면_정확명으로_보지_않는다(self):
        self.assertIsNone(recover_specific_place(["오늘", "도서관", "차 좀 불러줘"]))

    def test_분석기가_specific_place를_직접_주면_그_값을_쓴다(self):
        result = CareCallResult.from_analyzer_output(
            {"specific_place": "중앙도서관", "extracted_keywords": ["사당솔밭도서관"]}
        )
        self.assertEqual(result.specific_place, "중앙도서관")


class GateTest(unittest.TestCase):
    def test_응급이면_목적지가_있어도_DRT를_부르지_않는다(self):
        decision = gate.evaluate(_result(emergency_risk=True, dialogue_stage="emergency"))
        self.assertEqual(decision.action, gate.ACTION_ESCALATE)
        self.assertFalse(decision.should_call_drt)

    def test_차량_호출을_거절하면_부르지_않는다(self):
        decision = gate.evaluate(_result(dialogue_stage="not_needed", reservation_consent="refused"))
        self.assertEqual(decision.action, gate.ACTION_SKIP)

    def test_예약_동의_전에는_미리_계획을_조회하지_않는다(self):
        # TMAP 쿼터를 동의 없이 쓰지 않기 위한 규칙.
        decision = gate.evaluate(_result(
            dialogue_stage="reservation_confirm", reservation_consent="not_confirmed",
            next_question="시장에 가시는 이동 차량 예약을 도와드릴까요?",
        ))
        self.assertEqual(decision.action, gate.ACTION_ASK_USER)
        self.assertIn("예약", decision.spoken)

    def test_목적지가_안_정해졌으면_되묻는다(self):
        decision = gate.evaluate(_result(missing_slots=["place_resolution_method", "date"]))
        self.assertEqual(decision.action, gate.ACTION_ASK_USER)
        self.assertTrue(decision.code.startswith("missing:place_resolution_method"))

    def test_날짜_시간_출발지_슬롯은_호출을_막지_않는다(self):
        # drt_service는 예약 시각을 받지 않고, 출발지는 등록 좌표를 쓰기 때문이다.
        decision = gate.evaluate(_result(missing_slots=["date", "time", "pickup_location"]))
        self.assertTrue(decision.should_call_drt)

    def test_어르신이_시각을_말씀하시면_경고를_남긴다(self):
        # "내일 오전 10시"인데 즉시 배차하면 안 되므로 기록에 남겨야 한다.
        decision = gate.evaluate(_result(missing_slots=["pickup_location"]))
        self.assertTrue(decision.should_call_drt)
        self.assertIn("schedule_hint_present", decision.notes)

    def test_시각을_말씀하지_않으면_경고가_없다(self):
        decision = gate.evaluate(_result(missing_slots=["date", "time"]))
        self.assertNotIn("schedule_hint_present", decision.notes)


if __name__ == "__main__":
    unittest.main()
