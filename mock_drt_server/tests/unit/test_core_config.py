import unittest
from unittest.mock import patch

from app.core.config import _read_float, _read_int, _read_string


class CoreConfigTest(unittest.TestCase):
    def test_environment_value_overrides_default(self):
        with patch.dict("os.environ", {"TEST_SETTING": "42"}):
            self.assertEqual(_read_int("TEST_SETTING", 1, minimum=1), 42)

    def test_integer_setting_rejects_invalid_value(self):
        with patch.dict("os.environ", {"TEST_SETTING": "invalid"}):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                _read_int("TEST_SETTING", 1, minimum=1)

    def test_integer_setting_enforces_minimum(self):
        with patch.dict("os.environ", {"TEST_SETTING": "0"}):
            with self.assertRaisesRegex(ValueError, "at least 1"):
                _read_int("TEST_SETTING", 1, minimum=1)

    def test_float_setting_enforces_minimum(self):
        with patch.dict("os.environ", {"TEST_SETTING": "0"}):
            with self.assertRaisesRegex(ValueError, "at least 0.1"):
                _read_float("TEST_SETTING", 1.0, minimum=0.1)

    def test_string_setting_rejects_blank_value(self):
        with patch.dict("os.environ", {"TEST_SETTING": " "}):
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                _read_string("TEST_SETTING", "default")

    def test_string_setting_can_allow_empty_value(self):
        with patch.dict("os.environ", {"TEST_SETTING": ""}):
            self.assertEqual(
                _read_string("TEST_SETTING", "default", allow_empty=True),
                "",
            )


if __name__ == "__main__":
    unittest.main()
