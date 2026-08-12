"""배차 결과(도착예정시간·조회 링크)가 어르신과 보호자에게 닿는지 검증.

drt_service에 배차 서버가 연결되면 예약 응답에 tracking_url·estimated_arrival_s가
실려 온다. 그 값이 음성 안내와 문자로 제대로 이어지는지 확인한다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from bridge import notify, speech
from bridge.config import BASE_DIR, Settings
from bridge.fake_service import FakeDrtService
from bridge.location import ProfileStore
from bridge.notify import ROLE_ELDER, ROLE_GUARDIAN, RecordingSmsSender, SmsMessage
from bridge.orchestrator import ACTION_RESERVED, DrtHandoff

try:
    import clawops  # bridge 코어는 표준 라이브러리만 쓰지만, ClawOpsSmsSender 자체가
    # 선택 의존성이므로 이 테스트도 없으면 건너뛴다(RecordingSmsSender 쪽 테스트는
    # 그대로 설치 없이 돈다).
except ModuleNotFoundError:
    clawops = None

SAMPLES = BASE_DIR / "samples"


def load_sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


class ArrivalSpeechTest(unittest.TestCase):
    def test_도착예정시간을_분으로_알려_준다(self):
        response = {"ok": True, "reservation": {"call_id": "CALL-1", "estimated_arrival_s": 132}}
        utterance = speech.spoken_for_reservation(response, "남성역")
        self.assertIn("약 2분 뒤에", utterance.text)
        self.assertIn("남성역", utterance.text)

    def test_1분_미만은_곧이라고_말한다(self):
        # "약 0분"이나 "약 1분"이라고 하면 시계를 보고 기다리시게 된다.
        response = {"ok": True, "reservation": {"call_id": "CALL-1", "estimated_arrival_s": 40}}
        self.assertIn("곧", speech.spoken_for_reservation(response, "남성역").text)

    def test_도착예정시간이_없으면_기존_안내를_쓴다(self):
        # 배차 서버를 쓰지 않는 MOCK 모드.
        response = {"ok": True, "reservation": {"call_id": "abc123"}}
        self.assertIn("기다려 주세요", speech.spoken_for_reservation(response, "남성역").text)

    def test_조회_링크와_호출번호는_읽지_않는다(self):
        response = {"ok": True, "reservation": {
            "call_id": "CALL-B557DE10",
            "estimated_arrival_s": 132,
            "tracking_url": "http://localhost:8000/tracking/wZqrahwI1Cv",
        }}
        text = speech.spoken_for_reservation(response, "남성역").text
        self.assertNotIn("CALL-B557DE10", text)
        self.assertNotIn("tracking", text)
        self.assertNotIn("http", text)


class MessageBuildTest(unittest.TestCase):
    RESERVATION = {
        "call_id": "CALL-1",
        "estimated_arrival_s": 132,
        "tracking_url": "http://localhost:8000/tracking/abc",
        "tracking_message": "DRT 예약이 완료되었습니다.\n승차 장소: 남성역\nhttp://localhost:8000/tracking/abc",
    }
    PLAN = {"boarding": {"name": "남성역"}, "destination": {"name": "남현서울정형외과"}}

    def test_어르신에게는_배차서버_문구를_그대로_보낸다(self):
        messages = notify.build_messages(
            self.RESERVATION, self.PLAN, elder_contact="010-0000-0001",
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, ROLE_ELDER)
        self.assertIn("남성역", messages[0].text)

    def test_보호자_동의가_없으면_보내지_않는다(self):
        messages = notify.build_messages(
            self.RESERVATION, self.PLAN,
            elder_contact="010-0000-0001", guardian_contact="010-0000-0002",
            guardian_notify_consent="not_asked",
        )
        self.assertEqual([m.role for m in messages], [ROLE_ELDER])

    def test_보호자_동의가_있으면_함께_보낸다(self):
        messages = notify.build_messages(
            self.RESERVATION, self.PLAN, elder_name="김복순",
            elder_contact="010-0000-0001", guardian_contact="010-0000-0002",
            guardian_notify_consent="confirmed",
        )
        self.assertEqual([m.role for m in messages], [ROLE_ELDER, ROLE_GUARDIAN])
        보호자문자 = messages[1].text
        self.assertIn("김복순 어르신", 보호자문자)
        self.assertIn("남현서울정형외과", 보호자문자)
        self.assertIn("약 2분", 보호자문자)
        self.assertIn("http://localhost:8000/tracking/abc", 보호자문자)

    def test_조회_링크가_없으면_문자를_만들지_않는다(self):
        # 배차 서버를 쓰지 않는 MOCK 모드에서는 보낼 것이 없다.
        messages = notify.build_messages(
            {"call_id": "abc"}, self.PLAN,
            elder_contact="010-0000-0001", guardian_contact="010-0000-0002",
            guardian_notify_consent="confirmed",
        )
        self.assertEqual(messages, [])


class HandoffNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config = Settings(
            profiles_path=BASE_DIR / "data" / "user_profiles.json",
            audit_log_path=Path(self._tmp.name) / "handoff.jsonl",
            sms_log_path=Path(self._tmp.name) / "sms.jsonl",
        )
        self.sender = RecordingSmsSender(self.config.sms_log_path)
        self.handoff = DrtHandoff(
            FakeDrtService(), ProfileStore.load(self.config.profiles_path),
            self.config, sms_sender=self.sender,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _reserve(self, sample: str = "01_nearby_market_ready.json", **overrides):
        payload = load_sample(sample)
        payload.update(overrides)
        self.handoff.handle_analysis("elder_demo_01", payload)
        return self.handoff.handle_reply("elder_demo_01", "응 불러줘")

    def test_예약되면_조회_링크와_문자가_함께_나온다(self):
        outcome = self._reserve()
        self.assertEqual(outcome.action, ACTION_RESERVED)
        self.assertTrue(outcome.tracking_url.startswith("http"))
        self.assertEqual([m.role for m in outcome.sms_messages], [ROLE_ELDER])
        self.assertIn("약 2분 뒤에", outcome.text)

    def test_보호자_동의가_있으면_보호자에게도_간다(self):
        outcome = self._reserve(guardian_notify_consent="confirmed")
        self.assertEqual(
            [m.role for m in outcome.sms_messages], [ROLE_ELDER, ROLE_GUARDIAN]
        )

    def test_문자_내용이_기록된다(self):
        self._reserve()
        lines = Path(self.config.sms_log_path).read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        self.assertEqual(entry["role"], ROLE_ELDER)
        # 실제 발송이 아님이 기록에 드러나야 한다.
        self.assertFalse(entry["delivered"])

    def test_예약하지_않으면_문자도_없다(self):
        self.handoff.handle_analysis("elder_demo_01", load_sample("01_nearby_market_ready.json"))
        outcome = self.handoff.handle_reply("elder_demo_01", "아니 됐어")
        self.assertEqual(outcome.sms_messages, [])
        self.assertEqual(self.sender.sent, [])

    def test_감사_로그에_링크_자체는_남기지_않는다(self):
        outcome = self._reserve()
        log = Path(self.config.audit_log_path).read_text(encoding="utf-8")
        self.assertNotIn(outcome.tracking_url, log)
        self.assertIn('"tracking_issued": true', log)


@unittest.skipUnless(clawops is not None, "clawops 패키지가 설치돼 있지 않음")
class ClawOpsSmsSenderTest(unittest.TestCase):
    """실제 네트워크 호출 없이 성공/실패 경로만 확인한다(클라이언트를 몽키패치)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "sms.jsonl"
        self.sender = notify.ClawOpsSmsSender(
            "sk_test", "AC_test", "01000000000", log_path=self.log_path,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _log_entries(self) -> list[dict]:
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines]

    def test_접수되면_성공으로_기록한다(self):
        sent_kwargs = {}

        def fake_create(self_, **kwargs):
            sent_kwargs.update(kwargs)
            return clawops.types.message.Message(
                message_id="msg_1", status="queued", type="sms",
                to=kwargs["to"], from_=kwargs["from_"], num_media=0,
                direction="outbound", account_id="AC_test",
                date_created="2026-08-12T00:00:00Z",
            )

        # ClawOps.messages는 접근할 때마다 새 Messages 인스턴스를 만드는
        # property라, 인스턴스에 몽키패치를 걸어도 다음 접근에서 사라진다.
        # 클래스 메서드 자체를 patch해야 실제로 먹는다.
        with mock.patch.object(clawops.resources.Messages, "create", fake_create):
            ok = self.sender.send(SmsMessage(ROLE_ELDER, "01012345678", "예약 문구"))

        self.assertTrue(ok)
        self.assertEqual(sent_kwargs["to"], "01012345678")
        self.assertEqual(sent_kwargs["from_"], "01000000000")
        self.assertEqual(sent_kwargs["type"], "sms")  # 짧은 문구는 그대로 sms
        entry = self._log_entries()[-1]
        self.assertTrue(entry["delivered"])
        self.assertEqual(entry["message_id"], "msg_1")

    def test_200바이트_넘으면_LMS로_자동_전환한다(self):
        """실제 통화(2026-08-12)에서 재현된 버그: 예약 확정 문구(안내+조회 링크)가
        200바이트를 넘어 "SMS Body는 200byte를 초과할 수 없습니다"로 거절됐다."""
        sent_kwargs = {}

        def fake_create(self_, **kwargs):
            sent_kwargs.update(kwargs)
            return clawops.types.message.Message(
                message_id="msg_2", status="queued", type=kwargs["type"],
                to=kwargs["to"], from_=kwargs["from_"], num_media=0,
                direction="outbound", account_id="AC_test",
                date_created="2026-08-12T00:00:00Z",
            )

        long_text = (
            "이동 차량 예약이 완료되었습니다.\n승차 장소: 남성역\n"
            "아래 링크에서 차량 위치와 도착 예정시간을 확인해 주세요.\n"
            "https://mock-drt-server-4yf1.onrender.com/tracking?token=" + "a" * 40
        )
        self.assertGreater(len(long_text.encode("utf-8")), 200)

        with mock.patch.object(clawops.resources.Messages, "create", fake_create):
            ok = self.sender.send(SmsMessage(ROLE_ELDER, "01012345678", long_text))

        self.assertTrue(ok)
        self.assertEqual(sent_kwargs["type"], "lms")
        entry = self._log_entries()[-1]
        self.assertEqual(entry["type"], "lms")

    def test_API_오류가_나도_통화를_끊지_않고_실패로_기록한다(self):
        def fake_create(self_, **kwargs):
            raise clawops.AuthenticationError(
                "invalid api key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://api.claw-ops.com/messages")),
                body=None,
            )

        with mock.patch.object(clawops.resources.Messages, "create", fake_create):
            ok = self.sender.send(SmsMessage(ROLE_ELDER, "01012345678", "예약 문구"))

        self.assertFalse(ok)
        entry = self._log_entries()[-1]
        self.assertFalse(entry["delivered"])
        self.assertIn("AuthenticationError", entry["error"])


if __name__ == "__main__":
    unittest.main()
