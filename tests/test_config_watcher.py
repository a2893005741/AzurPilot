import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from module.config.watcher import ConfigWatcher


class TestConfigWatcher(unittest.TestCase):
    def test_detects_change_within_same_second(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "alas.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write("{}")

            watcher = ConfigWatcher()
            watcher.config_name = "alas"
            with patch("module.config.watcher.filepath_config", return_value=path):
                watcher.start_watching()
                start_mtime = watcher.start_mtime
                changed_mtime = start_mtime.replace(
                    microsecond=min(start_mtime.microsecond + 100_000, 999_999)
                )
                os.utime(path, (changed_mtime.timestamp(), changed_mtime.timestamp()))

                self.assertGreater(watcher.get_mtime(), start_mtime)
                self.assertTrue(watcher.should_reload())


if __name__ == "__main__":
    unittest.main()
