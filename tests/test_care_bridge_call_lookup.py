"""CareCallBridge의 실제 전화번호 확보 로직 검증(웹훅 매칭 + calls.list() 폴백).

**2026-08-12 배경**: ClawOps 웹훅(agent.connected 등)이 실제로는 발생하지 않는
것이 확인돼(발송 기록 0건), 사용자 결정으로 calls.list() 폴백을 임시로 추가했다.
이 폴백은 "지금 진행 중인 통화가 하나뿐"이라는 안전하지 않은 가정을 쓰므로,
동시 다발 통화 운영 전에는 웹훅 방식으로 대체돼야 한다(care_bridge.py 참고).
"""
from __future__ import annotations

import unittest
from unittest import mock

try:
    import clawops
except ModuleNotFoundError:
    clawops = None

from bridge.config import settings as bridge_settings


def _fake_call(to: str) -> "clawops.types.call.Call":
    return clawops.types.call.Call(
        call_id="CA1", status="in-progress", to=to, from_="07052753804",
        direction="outbound", account_id="AC_test", date_created="2026-08-12T00:00:00Z",
    )


@unittest.skipUnless(clawops is not None, "clawops 패키지가 설치돼 있지 않음")
class RecentCallLookupTest(unittest.TestCase):
    """bridge_settings 싱글턴을 잠깐 patch해 자격증명이 있는 상태를 흉내낸다."""

    def setUp(self) -> None:
        self._patches = [
            mock.patch.object(bridge_settings, "clawops_api_key", "sk_test"),
            mock.patch.object(bridge_settings, "clawops_account_id", "AC_test"),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self._patches:
            patch.stop()

    def _new_bridge(self):
        from main_server.care_bridge import CareCallBridge

        return CareCallBridge()

    def test_진행중인_통화가_있으면_번호를_가져온다(self):
        care = self._new_bridge()
        self.assertIsNotNone(care._clawops_client)

        def fake_list(self_, **kwargs):
            return clawops.pagination.SyncPage(
                data=[_fake_call("01099998888")],
                meta={"page": 0, "page_size": 1, "total": 1},
            )

        with mock.patch.object(clawops.resources.Calls, "list", fake_list):
            care.start_call("CALL-X", "elder_demo_01", "")

        self.assertEqual(care._sessions["CALL-X"].elder_phone, "01099998888")

    def test_진행중인_통화가_없으면_None(self):
        care = self._new_bridge()

        def fake_list_empty(self_, **kwargs):
            return clawops.pagination.SyncPage(data=[], meta={"page": 0, "page_size": 1, "total": 0})

        with mock.patch.object(clawops.resources.Calls, "list", fake_list_empty):
            care.start_call("CALL-Y", "elder_demo_01", "")

        self.assertIsNone(care._sessions["CALL-Y"].elder_phone)

    def test_API_오류가_나도_통화_시작을_막지_않는다(self):
        care = self._new_bridge()

        def fake_list_error(self_, **kwargs):
            raise clawops.APIConnectionError(message="연결 실패")

        with mock.patch.object(clawops.resources.Calls, "list", fake_list_error):
            greeting = care.start_call("CALL-Z", "elder_demo_01", "")

        self.assertTrue(greeting)  # 인사말은 정상적으로 나와야 한다
        self.assertIsNone(care._sessions["CALL-Z"].elder_phone)

    def test_웹훅으로_이미_받은_번호가_있으면_calls_list를_안_부른다(self):
        care = self._new_bridge()
        care.pending_calls.store("CA-KNOWN", "01011112222")

        def fail_if_called(self_, **kwargs):
            raise AssertionError("웹훅으로 이미 확보된 경우 calls.list()를 부르면 안 된다")

        with mock.patch.object(clawops.resources.Calls, "list", fail_if_called):
            care.start_call("CALL-W", "elder_demo_01", "CA-KNOWN")

        self.assertEqual(care._sessions["CALL-W"].elder_phone, "01011112222")


if __name__ == "__main__":
    unittest.main()
