"""분석 결과 -> DRT 호출 -> 음성 응답까지 전체 흐름 검증.

가짜 DRT 서버(bridge/fake_service.py)를 쓰므로 drt_service를 띄우지 않아도 된다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bridge.config import BASE_DIR, Settings
from bridge.fake_service import FakeDrtService
from bridge.location import ProfileStore
from bridge.orchestrator import (
    ACTION_ESCALATE,
    ACTION_RESERVED,
    ACTION_SKIP,
    ACTION_SPEAK,
    DrtHandoff,
)

SAMPLES = BASE_DIR / "samples"

# drt_service의 PlanRequest가 허용하는 키. extra="forbid"라서 이 밖의 키를 보내면 422가 난다.
ALLOWED_PAYLOAD_KEYS = {
    "latitude", "longitude", "accuracy", "captured_at",
    "max_walk_m", "query", "is_specific", "expected_wait_s", "weather", "speed_level",
}


def load_sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


class HandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = Settings(
            profiles_path=BASE_DIR / "data" / "user_profiles.json",
            audit_log_path=Path(self._tmp.name) / "handoff_log.jsonl",
        )
        self.config = config
        self.service = FakeDrtService()
        self.handoff = DrtHandoff(
            self.service, ProfileStore.load(config.profiles_path), config
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── 안전 장치 ──────────────────────────────────────────────────────────

    def test_응급_상황에서는_DRT를_한_번도_부르지_않는다(self):
        outcome = self.handoff.handle_analysis("elder_demo_01", load_sample("05_emergency_fall.json"))
        self.assertEqual(outcome.action, ACTION_ESCALATE)
        self.assertEqual(self.service.plan_calls, [])
        self.assertEqual(self.service.reserve_calls, [])

    def test_차량이_필요_없다고_하시면_부르지_않는다(self):
        outcome = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("06_family_ride_not_needed.json")
        )
        self.assertEqual(outcome.action, ACTION_SKIP)
        self.assertEqual(self.service.plan_calls, [])

    def test_위치정보_동의가_없으면_좌표를_보내지_않는다(self):
        # elder_demo_02는 location_consent=false.
        outcome = self.handoff.handle_analysis(
            "elder_demo_02", load_sample("01_nearby_market_ready.json")
        )
        self.assertEqual(outcome.code, "location_consent_missing")
        self.assertEqual(self.service.plan_calls, [])
        self.assertIn("위치", outcome.text)

    def test_등록되지_않은_사용자면_호출하지_않는다(self):
        outcome = self.handoff.handle_analysis("없는사람", load_sample("01_nearby_market_ready.json"))
        self.assertEqual(outcome.code, "profile_not_found")
        self.assertEqual(self.service.plan_calls, [])

    # ── 정상 흐름 ──────────────────────────────────────────────────────────

    def test_가까운_시장_요청이_대분류_검색으로_넘어간다(self):
        outcome = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("01_nearby_market_ready.json")
        )
        self.assertEqual(len(self.service.plan_calls), 1)
        payload = self.service.plan_calls[0]
        self.assertEqual(payload["query"], "시장")
        self.assertFalse(payload["is_specific"])
        self.assertEqual(payload["latitude"], 37.4849)
        self.assertEqual(outcome.action, ACTION_SPEAK)
        self.assertIn("불러 드릴까요", outcome.text)

    def test_요청_본문에_drt_service가_모르는_키를_넣지_않는다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        payload_keys = set(self.service.plan_calls[0])
        self.assertTrue(payload_keys <= ALLOWED_PAYLOAD_KEYS, payload_keys - ALLOWED_PAYLOAD_KEYS)

    def test_확인하시면_예약까지_진행한다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        outcome = self.handoff.handle_reply("elder_demo_01", "응, 불러줘")
        self.assertEqual(outcome.action, ACTION_RESERVED)
        self.assertEqual(len(self.service.reserve_calls), 1)
        # 예약 요청은 계획을 세울 때와 같은 본문이어야 한다.
        self.assertEqual(self.service.reserve_calls[0], self.service.plan_calls[0])

    def test_거절하시면_예약하지_않는다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        outcome = self.handoff.handle_reply("elder_demo_01", "아니, 됐어")
        self.assertEqual(outcome.action, ACTION_SKIP)
        self.assertEqual(self.service.reserve_calls, [])

    def test_대답이_애매하면_다시_묻고_예약하지_않는다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        outcome = self.handoff.handle_reply("elder_demo_01", "글쎄...")
        self.assertEqual(outcome.code, "confirm_unclear")
        self.assertEqual(self.service.reserve_calls, [])

    # ── 후보가 여러 곳일 때 ────────────────────────────────────────────────

    def test_후보를_고르시면_정확명으로_다시_검색한다(self):
        first = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("02_nearby_dental_multiple.json")
        )
        self.assertIn("사당연세치과", first.text)

        second = self.handoff.handle_reply("elder_demo_01", "연세치과로 가자")
        self.assertEqual(len(self.service.plan_calls), 2)
        재검색 = self.service.plan_calls[1]
        self.assertEqual(재검색["query"], "사당연세치과")
        self.assertTrue(재검색["is_specific"])
        # 출발 좌표는 처음 검색과 같아야 한다.
        self.assertEqual(재검색["latitude"], self.service.plan_calls[0]["latitude"])
        self.assertIn("불러 드릴까요", second.text)

    def test_서수로도_후보를_고를_수_있다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("02_nearby_dental_multiple.json"))
        self.handoff.handle_reply("elder_demo_01", "두 번째로 해줘")
        self.assertEqual(self.service.plan_calls[1]["query"], "남성역바른치과")

    def test_후보가_비어_있으면_빈_문장을_말하지_않는다(self):
        # 예전에는 "중에 어디로 모실까요?"라는 깨진 문장이 나갔다.
        session = self.handoff.sessions.get("elder_demo_01")
        session.awaiting = "destination_choice"
        session.candidates = []
        outcome = self.handoff.handle_reply("elder_demo_01", "응 불러줘")
        self.assertEqual(outcome.code, "awaiting_new_destination")
        self.assertNotIn("중에", outcome.text)
        self.assertEqual(outcome.expects, "")

    def test_못_알아들으면_후보를_다시_읽어_준다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("02_nearby_dental_multiple.json"))
        outcome = self.handoff.handle_reply("elder_demo_01", "음...")
        self.assertEqual(outcome.code, "choice_unclear")
        self.assertEqual(len(self.service.plan_calls), 1)

    # ── 그 밖의 분기 ───────────────────────────────────────────────────────

    def test_목적지가_안_정해졌으면_되묻고_호출하지_않는다(self):
        outcome = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("04_senior_center_unresolved.json")
        )
        self.assertEqual(self.service.plan_calls, [])
        self.assertIn("경로당", outcome.text)

    def test_예약_시각이_있으면_경고를_남긴다(self):
        # drt_service는 "내일 오후 1시" 예약을 받지 못하는 즉시 호출 모델이다.
        outcome = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("03_exact_library_scheduled.json")
        )
        self.assertIn("schedule_hint_present", outcome.notes)
        self.assertEqual(self.service.plan_calls[0]["query"], "사당솔밭도서관")
        self.assertTrue(self.service.plan_calls[0]["is_specific"])

    def test_가까운_목적지는_걸어가시라고_안내한다(self):
        outcome = self.handoff.handle_analysis(
            "elder_demo_01", load_sample("03_exact_library_scheduled.json")
        )
        self.assertIn("가까워서", outcome.text)
        self.assertEqual(outcome.expects, "")
        # 도보 추천이므로 예약 확인을 기다리지 않는다.
        self.assertEqual(self.handoff.handle_reply("elder_demo_01", "응").action, ACTION_SKIP)

    def test_감사_로그가_남는다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        lines = Path(self.config.audit_log_path).read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertEqual(entry["user_id"], "elder_demo_01")
        self.assertEqual(entry["query"], "시장")


if __name__ == "__main__":
    unittest.main()
