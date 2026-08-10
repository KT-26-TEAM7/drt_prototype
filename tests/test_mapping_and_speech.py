"""검색어 변환과 음성 문장 생성 검증."""
from __future__ import annotations

import unittest

from bridge import mapping, speech
from bridge.contract import CareCallResult


def _result(**overrides) -> CareCallResult:
    return CareCallResult.from_analyzer_output(overrides)


class MappingTest(unittest.TestCase):
    def test_가까운_곳_검색은_대분류_검색어가_된다(self):
        plan = mapping.build_query(_result(search_mode="nearby_search", search_keywords=["시장"]))
        self.assertIsInstance(plan, mapping.QueryPlan)
        self.assertEqual(plan.query, "시장")
        self.assertFalse(plan.is_specific)

    def test_정확명이_있으면_정확명_검색이_된다(self):
        plan = mapping.build_query(_result(
            search_mode="exact_place", extracted_keywords=["사당솔밭도서관"],
        ))
        self.assertEqual(plan.query, "사당솔밭도서관")
        self.assertTrue(plan.is_specific)

    def test_정확명_검색인데_이름이_없으면_되묻는다(self):
        result = mapping.build_query(_result(search_mode="exact_place", extracted_keywords=["내일"]))
        self.assertIsInstance(result, mapping.QueryUnavailable)
        self.assertEqual(result.code, "specific_place_missing")

    def test_아직_안_정해진_검색_방식은_분석기_질문을_그대로_돌려준다(self):
        질문 = "평소 자주 가시는 경로당이 있으실까요?"
        result = mapping.build_query(_result(
            search_mode="ask_frequent_or_nearby", place_resolution_question=질문,
        ))
        self.assertIsInstance(result, mapping.QueryUnavailable)
        self.assertEqual(result.spoken, 질문)

    def test_검색어가_없으면_카테고리에서_장소_이름을_만든다(self):
        plan = mapping.build_query(_result(
            search_mode="nearby_search", destination_category="medical_dental",
        ))
        self.assertEqual(plan.query, "치과")


class SpeechTest(unittest.TestCase):
    def test_영어_약어는_우리말로_바꿔_읽는다(self):
        # system_prompt.txt가 영어를 금지하므로 "DRT"를 그대로 읽으면 안 된다.
        self.assertEqual(speech.sanitize("DRT 차량을 부를까요?"), "이동 차량 차량을 부를까요?")

    def test_한자와_이모지는_지운다(self):
        # 모델 비교 과정에서 LLM이 답변 끝에 한자를 흘린 사례가 있었다.
        self.assertEqual(speech.sanitize("많이 힘드시겠어요.法"), "많이 힘드시겠어요.")

    def test_목적지_이름의_영문은_지우지_않고_보고만_한다(self):
        문장 = speech.sanitize("GS편의점으로 모실까요?")
        self.assertIn("GS편의점", 문장)
        self.assertEqual(speech.tts_violations(문장), ["G", "S"])

    def test_브릿지가_만든_문장에는_금지_문자가_없다(self):
        plan = {
            "status": "ready_for_confirmation",
            "destination": {"name": "사당종합복지관"},
            "boarding": {"name": "남성역"},
            "total_travel_time_s": 745,
        }
        utterance = speech.spoken_for_plan(plan)
        self.assertEqual(speech.tts_violations(utterance.text), [])
        self.assertIn("약 12분", utterance.text)
        self.assertEqual(utterance.expects, speech.EXPECT_RESERVATION_CONFIRM)

    def test_후보가_여러_곳이면_이름을_읽어_주고_선택을_기다린다(self):
        plan = {
            "status": "needs_destination_confirmation",
            "candidates": [{"name": "사당연세치과"}, {"name": "남성역바른치과"}],
        }
        utterance = speech.spoken_for_plan(plan)
        self.assertIn("사당연세치과", utterance.text)
        self.assertEqual(utterance.expects, speech.EXPECT_DESTINATION_CHOICE)

    def test_읽어_주는_후보_수를_제한한다(self):
        plan = {
            "status": "needs_destination_confirmation",
            "candidates": [{"name": f"치과{i}"} for i in range(5)],
        }
        utterance = speech.spoken_for_plan(plan, max_candidates=2)
        self.assertIn("치과0", utterance.text)
        self.assertNotIn("치과2", utterance.text)

    def test_목적지_이름에_맞는_조사를_고른다(self):
        # "정형외과으로", "정형외과은"처럼 틀리면 음성으로 바로 귀에 걸린다.
        self.assertEqual(speech.direction_particle("남현서울정형외과"), "로")
        self.assertEqual(speech.direction_particle("사당종합복지관"), "으로")
        self.assertEqual(speech.direction_particle("사당솔밭도서관"), "으로")
        self.assertEqual(speech.topic_particle("남현서울정형외과"), "는")
        self.assertEqual(speech.topic_particle("사당솔밭도서관"), "은")

    def test_받침_없는_목적지_안내에_로를_쓴다(self):
        utterance = speech.spoken_for_plan({
            "status": "ready_for_confirmation",
            "destination": {"name": "남현서울정형외과"},
            "boarding": {"name": "남성역"},
            "total_travel_time_s": 600,
        })
        self.assertIn("남현서울정형외과로 가시는", utterance.text)
        self.assertNotIn("정형외과으로", utterance.text)

    def test_고를_후보가_없으면_선택을_기다리지_않는다(self):
        # 빈 후보로 선택을 기다리면 "중에 어디로 모실까요?" 같은 깨진 문장이 나간다.
        # 새 목적지 추출은 케어콜 분석기의 몫이므로 다음 턴 분석 결과로 넘긴다.
        for status in ("destination_not_found", "destination_outside_service_area",
                       "no_feasible_destination"):
            utterance = speech.spoken_for_plan({"status": status})
            self.assertEqual(utterance.expects, speech.EXPECT_NONE, status)
            self.assertTrue(utterance.text)

    def test_도보_추천이면_예약을_묻지_않는다(self):
        plan = {
            "status": "walk_recommended",
            "destination": {"name": "사당솔밭도서관"},
            "direct_walk": {"duration_s": 300},
        }
        utterance = speech.spoken_for_plan(plan)
        self.assertEqual(utterance.expects, speech.EXPECT_NONE)
        self.assertIn("5분", utterance.text)

    def test_예약_번호는_읽지_않는다(self):
        # 전화로 들으신 어르신이 받아 적을 수 없는 값이다.
        response = {"ok": True, "reservation": {"call_id": "a1b2c3d4e5f6", "status": "accepted"}}
        utterance = speech.spoken_for_reservation(response, "남성역")
        self.assertNotIn("a1b2c3", utterance.text)
        self.assertIn("남성역", utterance.text)


if __name__ == "__main__":
    unittest.main()
