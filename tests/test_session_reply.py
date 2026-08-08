"""되물음에 대한 어르신 답변을 알아듣는지 검증.

전화 통화라 답변이 짧고 조사가 붙는다("연세치과로 가자"). 여기서 못 알아들으면
브릿지가 계속 같은 질문을 반복하게 된다.
"""
from __future__ import annotations

import unittest

from bridge.session import parse_choice, parse_yes_no

CANDIDATES = [
    {"name": "사당연세치과"},
    {"name": "남성역바른치과"},
    {"name": "동작예치과"},
]


class YesNoTest(unittest.TestCase):
    def test_동의_표현(self):
        for text in ("응", "그래 해줘", "네 불러주세요", "그렇게 해줘"):
            self.assertIs(parse_yes_no(text), True, text)

    def test_거절_표현(self):
        for text in ("아니", "됐어", "안 해도 돼", "괜찮아 그만"):
            self.assertIs(parse_yes_no(text), False, text)

    def test_거절이_섞이면_거절로_본다(self):
        # 안전한 쪽으로 판단한다. 원치 않는 배차가 나가는 것보다 다시 묻는 편이 낫다.
        self.assertIs(parse_yes_no("아니 괜찮아 그래도 고마워"), False)

    def test_애매하면_판단하지_않는다(self):
        for text in ("글쎄", "음...", ""):
            self.assertIsNone(parse_yes_no(text), text)


class ChoiceTest(unittest.TestCase):
    def test_서수로_고르기(self):
        self.assertEqual(parse_choice("첫 번째", CANDIDATES), 0)
        self.assertEqual(parse_choice("두 번째로 해줘", CANDIDATES), 1)
        self.assertEqual(parse_choice("세번째", CANDIDATES), 2)

    def test_이름을_통째로_말씀하시는_경우(self):
        self.assertEqual(parse_choice("남성역바른치과로 가줘", CANDIDATES), 1)

    def test_이름_일부와_조사가_붙는_경우(self):
        self.assertEqual(parse_choice("연세치과로 가자", CANDIDATES), 0)
        self.assertEqual(parse_choice("동작예치과에 가고 싶어", CANDIDATES), 2)

    def test_여러_곳에_해당하는_말은_고른_것으로_보지_않는다(self):
        # "치과"는 세 곳 모두에 해당하므로 다시 여쭤야 한다.
        self.assertIsNone(parse_choice("치과로 가자", CANDIDATES))

    def test_없는_후보를_말씀하시면_판단하지_않는다(self):
        self.assertIsNone(parse_choice("서울대병원", CANDIDATES))

    def test_후보_수보다_큰_서수는_무시한다(self):
        self.assertIsNone(parse_choice("세 번째", CANDIDATES[:2]))


if __name__ == "__main__":
    unittest.main()
