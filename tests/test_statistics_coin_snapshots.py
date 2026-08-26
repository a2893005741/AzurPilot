import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from module.statistics.cl1_database import Cl1Database
from module.statistics import opsi_month, resource_stats


class TestCoinSnapshotRetention(unittest.TestCase):
    def test_keeps_complete_month_history_beyond_500_snapshots(self):
        with TemporaryDirectory() as tmp_dir:
            database = Cl1Database(Path(tmp_dir) / "cl1_data.db")
            for value in range(501):
                database.add_coins_snapshot(
                    "alas",
                    yellow_coins=value,
                    purple_coins=10000 + value,
                    source="test",
                )

            month = datetime.now().strftime("%Y-%m")
            snapshots = database.get_stats("alas", month)["coins_snapshots"]

        self.assertEqual(501, len(snapshots))
        self.assertEqual(0, snapshots[0]["yellow_coins"])
        self.assertEqual(10500, snapshots[-1]["purple_coins"])


class TestCoinTimelineRecovery(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.resource_db = Path(self.temporary_directory.name) / "azurstats_local.db"
        self.original_resource_db = resource_stats._LOCAL_DB
        self.original_table_ensured = resource_stats._table_ensured
        resource_stats._LOCAL_DB = str(self.resource_db)
        resource_stats._table_ensured = False
        resource_stats._ensure_table()

    def tearDown(self):
        resource_stats._LOCAL_DB = self.original_resource_db
        resource_stats._table_ensured = self.original_table_ensured
        self.temporary_directory.cleanup()

    def _insert_snapshot(self, timestamp, yellow_coin, purple_coin):
        with resource_stats._connect() as connection:
            connection.execute(
                """
                INSERT INTO resource_snapshots (
                    instance, ts, yellow_coin, purple_coin
                ) VALUES (?, ?, ?, ?)
                """,
                ("alas", timestamp, yellow_coin, purple_coin),
            )
            connection.commit()

    def test_resource_range_is_half_open_sorted_and_skips_invalid_timestamps(self):
        self._insert_snapshot("2026-07-31T23:59:59", 1, 10)
        self._insert_snapshot("2026-08-02T12:00:00", 3, 30)
        self._insert_snapshot("invalid", 999, 999)
        self._insert_snapshot("2026-08-01T00:00:00", 2, 20)
        self._insert_snapshot("2026-09-01T00:00:00", 4, 40)

        timeline = resource_stats.get_resource_timeline_range(
            "alas",
            datetime(2026, 8, 1),
            datetime(2026, 9, 1),
        )

        self.assertEqual(
            ["2026-08-01T00:00:00", "2026-08-02T12:00:00"],
            [item["ts"] for item in timeline],
        )

    def test_coins_timeline_prefers_complete_resource_history(self):
        self._insert_snapshot("2026-08-01T00:00:00", 2, 20)
        self._insert_snapshot("2026-08-02T12:00:00", None, 30)

        with patch.object(
            opsi_month.cl1_db,
            "get_stats",
            return_value={
                "coins_snapshots": [
                    {
                        "ts": "2026-08-25T12:00:00",
                        "yellow_coins": 500,
                        "purple_coins": 50,
                    }
                ]
            },
        ):
            timeline = opsi_month.get_coins_timeline(2026, 8, "alas")

        self.assertEqual(1, len(timeline))
        self.assertEqual(
            {
                "ts": "2026-08-01T00:00:00",
                "yellow_coins": 2,
                "purple_coins": 20,
                "source": "resource",
            },
            timeline[0],
        )

    def test_coins_timeline_falls_back_when_all_resource_rows_are_partial(self):
        self._insert_snapshot("2026-08-01T00:00:00", 2, None)
        self._insert_snapshot("2026-08-02T12:00:00", None, 30)
        fallback = [
            {
                "ts": "2026-08-25T12:00:00",
                "yellow_coins": 500,
                "purple_coins": 50,
                "source": "cl1",
            }
        ]

        with patch.object(
            opsi_month.cl1_db,
            "get_stats",
            return_value={"coins_snapshots": fallback},
        ):
            timeline = opsi_month.get_coins_timeline(2026, 8, "alas")

        self.assertEqual(fallback, timeline)

    def test_coins_timeline_falls_back_to_cl1_when_resource_history_is_empty(self):
        fallback = [
            {
                "ts": "2026-08-25T12:00:00",
                "yellow_coins": 500,
                "purple_coins": 50,
                "source": "cl1",
            }
        ]
        with patch.object(
            opsi_month.cl1_db,
            "get_stats",
            return_value={"coins_snapshots": fallback},
        ):
            timeline = opsi_month.get_coins_timeline(2026, 8, "alas")

        self.assertEqual(fallback, timeline)


if __name__ == "__main__":
    unittest.main()
