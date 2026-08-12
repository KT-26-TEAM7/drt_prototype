"""ClawOps 통화 상태 웹훅의 call_id<->전화번호 매칭 로직 검증.

실제 웹훅 서명/HTTP 계층은 main_server가 뜬 상태에서만 확인 가능하므로, 여기서는
표준 라이브러리만으로 순수 로직(저장소·페이로드 파싱)만 검증한다.
"""
from __future__ import annotations

import time
import unittest

from main_server.clawops_webhook import PendingCallRegistry, extract_call_id_and_phone, parse_payload


class PendingCallRegistryTest(unittest.TestCase):
    def test_저장한_번호를_call_id로_찾는다(self):
        registry = PendingCallRegistry()
        registry.store("CA123", "010-1234-5678")
        self.assertEqual(registry.claim("CA123"), "010-1234-5678")

    def test_claim하면_한_번만_쓰인다(self):
        registry = PendingCallRegistry()
        registry.store("CA123", "010-1234-5678")
        registry.claim("CA123")
        self.assertIsNone(registry.claim("CA123"))

    def test_없는_call_id는_None(self):
        registry = PendingCallRegistry()
        self.assertIsNone(registry.claim("없음"))

    def test_call_id나_번호가_비어있으면_저장하지_않는다(self):
        registry = PendingCallRegistry()
        registry.store("", "010-1234-5678")
        registry.store("CA123", "")
        self.assertIsNone(registry.claim("CA123"))

    def test_TTL이_지나면_사라진다(self):
        registry = PendingCallRegistry()
        registry.store("CA123", "010-1234-5678")
        # 내부 TTL은 10분이라 직접 만료시키기 위해 저장 시각을 과거로 조작한다.
        with registry._lock:
            entry = registry._entries["CA123"]
            registry._entries["CA123"] = entry.__class__(entry.phone, time.monotonic() - 1000)
        self.assertIsNone(registry.claim("CA123"))


class PayloadParsingTest(unittest.TestCase):
    def test_form_urlencoded을_파싱한다(self):
        fields = parse_payload(
            "application/x-www-form-urlencoded",
            b"CallSid=CA123&To=%2B821012345678&CallStatus=ringing",
        )
        self.assertEqual(fields["CallSid"], "CA123")
        self.assertEqual(fields["To"], "+821012345678")
        self.assertEqual(fields["CallStatus"], "ringing")

    def test_json을_파싱한다(self):
        fields = parse_payload(
            "application/json",
            b'{"call_id": "CA123", "to": "01012345678", "status": "in-progress"}',
        )
        self.assertEqual(fields["call_id"], "CA123")
        self.assertEqual(fields["to"], "01012345678")

    def test_빈_바디도_안_죽는다(self):
        self.assertEqual(parse_payload("application/json", b""), {})
        self.assertEqual(parse_payload("application/x-www-form-urlencoded", b""), {})


class ExtractCallIdAndPhoneTest(unittest.TestCase):
    def test_snake_case_필드명(self):
        call_id, phone, status = extract_call_id_and_phone(
            {"call_id": "CA123", "to": "01012345678", "status": "ringing"}
        )
        self.assertEqual((call_id, phone, status), ("CA123", "01012345678", "ringing"))

    def test_twilio류_PascalCase_필드명(self):
        call_id, phone, status = extract_call_id_and_phone(
            {"CallSid": "CA123", "To": "01012345678", "CallStatus": "ringing"}
        )
        self.assertEqual((call_id, phone, status), ("CA123", "01012345678", "ringing"))

    def test_아무것도_없으면_빈_문자열(self):
        self.assertEqual(extract_call_id_and_phone({}), ("", "", ""))


if __name__ == "__main__":
    unittest.main()
