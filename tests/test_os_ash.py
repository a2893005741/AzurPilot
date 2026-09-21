import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from module.os_ash.ash import OSAsh


class TestAshCollectStatus(unittest.TestCase):
    def _status(self, collected, daily):
        ash = object.__new__(OSAsh)
        ash._ash_fully_collected = False
        ash.device = SimpleNamespace(image=object())
        ash.image_color_count = MagicMock(return_value=True)

        collected_ocr = MagicMock()
        collected_ocr.ocr.return_value = (collected, None, None)
        daily_ocr = MagicMock()
        daily_ocr.ocr.return_value = (daily, None, None)
        with patch('module.os_ash.ash.DigitCounter', return_value=collected_ocr), \
                patch('module.os_ash.ash.DailyDigitCounter', return_value=daily_ocr):
            result = ash.ash_collect_status()
        return ash, result

    def test_holding_cap_does_not_mark_daily_collection_complete(self):
        ash, result = self._status(collected=200, daily=100)

        self.assertEqual(result, 200)
        self.assertFalse(ash._ash_fully_collected)

    def test_daily_cap_marks_collection_complete(self):
        ash, result = self._status(collected=100, daily=200)

        self.assertEqual(result, 0)
        self.assertTrue(ash._ash_fully_collected)


if __name__ == '__main__':
    unittest.main()
