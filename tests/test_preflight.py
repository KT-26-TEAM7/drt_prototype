"""포트 설정이 어긋났을 때 잡아내는지 검증.

배차 서버의 리슨 포트와 조회 링크 주소(TRACKING_BASE_URL)는 서로 다른 설정이라
어긋날 수 있고, 어긋나면 어르신이 문자를 눌러 봐야 문제가 드러난다.
네트워크가 필요한 점검은 여기서 다루지 않고, 판정 로직만 확인한다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bridge import preflight
from bridge.config import BASE_DIR, Settings
from bridge.fake_service import FakeDrtService
from bridge.location import ProfileStore
from bridge.orchestrator import DrtHandoff

SAMPLES = BASE_DIR / "samples"


class SameOriginTest(unittest.TestCase):
    def test_localhost와_127_0_0_1은_같은_곳으로_본다(self):
        self.assertTrue(preflight.same_origin("http://localhost:8000", "http://127.0.0.1:8000"))

    def test_포트가_다르면_다른_곳이다(self):
        self.assertFalse(preflight.same_origin("http://127.0.0.1:8000", "http://127.0.0.1:8001"))

    def test_경로가_붙어_있어도_주소만_본다(self):
        self.assertTrue(preflight.same_origin(
            "http://localhost:8000/tracking/abc123", "http://127.0.0.1:8000"
        ))

    def test_기본_포트를_생략해도_비교된다(self):
        self.assertTrue(preflight.same_origin("http://example.com", "http://example.com:80"))
        self.assertFalse(preflight.same_origin("http://example.com", "http://example.com:8000"))


class TrackingWarningTest(unittest.TestCase):
    DRT = "http://127.0.0.1:8001"

    def test_링크가_drt_service를_가리키면_경고한다(self):
        # 배차 서버 TRACKING_BASE_URL이 drt_service 포트로 잘못 설정된 상황.
        warning = preflight.tracking_url_warning("http://localhost:8001/tracking/abc", self.DRT)
        self.assertEqual(warning, "tracking_url_points_to_drt_service")

    def test_정상_링크는_경고하지_않는다(self):
        self.assertEqual(
            preflight.tracking_url_warning("http://localhost:8000/tracking/abc", self.DRT), ""
        )

    def test_공개_도메인은_경고하지_않는다(self):
        # 역방향 프록시로 배포하면 링크 호스트가 배차 서버와 달라도 정상이다.
        self.assertEqual(
            preflight.tracking_url_warning("https://drt.example.com/tracking/abc", self.DRT), ""
        )


class BrokenLinkGuardTest(unittest.TestCase):
    """열리지 않을 링크는 문자로 내보내지 않는다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config = Settings(
            profiles_path=BASE_DIR / "data" / "user_profiles.json",
            audit_log_path=Path(self._tmp.name) / "handoff.jsonl",
            sms_log_path=Path(self._tmp.name) / "sms.jsonl",
            drt_base_url="http://127.0.0.1:8001",
        )
        self.service = FakeDrtService()
        self.handoff = DrtHandoff(
            self.service, ProfileStore.load(self.config.profiles_path), self.config
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _reserve(self):
        payload = json.loads((SAMPLES / "01_nearby_market_ready.json").read_text(encoding="utf-8"))
        self.handoff.handle_analysis("elder_demo_01", payload)
        return self.handoff.handle_reply("elder_demo_01", "응 불러줘")

    def test_정상_링크면_문자가_나간다(self):
        outcome = self._reserve()
        self.assertTrue(outcome.sms_messages)
        self.assertNotIn("tracking_url_points_to_drt_service", outcome.notes)

    def test_링크가_잘못되면_문자를_보내지_않는다(self):
        # 배차 서버가 drt_service 포트로 링크를 만들어 준 상황을 흉내 낸다.
        original = self.service.reserve

        def broken_reserve(payload):
            response = original(payload)
            response["reservation"]["tracking_url"] = "http://localhost:8001/tracking/abc"
            return response

        self.service.reserve = broken_reserve
        outcome = self._reserve()
        self.assertEqual(outcome.sms_messages, [])
        self.assertIn("tracking_url_points_to_drt_service", outcome.notes)
        # 예약 자체는 성공했으므로 음성 안내는 그대로 나간다.
        self.assertIn("차를 불러 드렸어요", outcome.text)


if __name__ == "__main__":
    unittest.main()
