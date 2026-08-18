import unittest
from datetime import datetime, timedelta

from module.config.config_updater import ConfigUpdater


class TestEmotionConfigRecovery(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 18, 12, 0, 0)

    def test_config_reload_recovers_stale_task_emotion_to_maximum(self):
        old = {
            'Main': {
                'Emotion': {
                    'Fleet1Value': 39,
                    'Fleet1Record': self.now - timedelta(hours=12),
                    'Fleet1Recover': 'not_in_dormitory',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)

        self.assertEqual(new['Main']['Emotion']['Fleet1Value'], 119)
        self.assertEqual(new['Main']['Emotion']['Fleet1Record'], self.now)

    def test_config_reload_preserves_fractional_recovery_time(self):
        old = {
            'Event': {
                'Emotion': {
                    'Fleet1Value': 40,
                    'Fleet1Record': self.now - timedelta(minutes=4),
                    'Fleet1Recover': 'not_in_dormitory',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)

        self.assertEqual(new['Event']['Emotion']['Fleet1Value'], 41)
        self.assertEqual(
            new['Event']['Emotion']['Fleet1Record'],
            self.now - timedelta(minutes=1),
        )

        reloaded = ConfigUpdater().config_update(
            new,
            now=self.now + timedelta(minutes=2),
        )
        self.assertEqual(reloaded['Event']['Emotion']['Fleet1Value'], 42)
        self.assertEqual(
            reloaded['Event']['Emotion']['Fleet1Record'],
            self.now + timedelta(minutes=2),
        )

    def test_config_reload_recovers_public_emotion(self):
        old = {
            'General': {
                'PublicEmotion': {
                    'FleetValue': 100,
                    'FleetRecord': self.now - timedelta(hours=2),
                    'FleetRecover': 'dormitory_floor_1',
                    'FleetOath': True,
                    'FleetOnsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)

        self.assertEqual(new['General']['PublicEmotion']['FleetValue'], 150)
        self.assertEqual(new['General']['PublicEmotion']['FleetRecord'], self.now)

    def test_dormitory_recovery_caps_fleet_emotion_at_150(self):
        old = {
            'Main': {
                'Emotion': {
                    'Fleet1Value': 39,
                    'Fleet1Record': self.now - timedelta(hours=12),
                    'Fleet1Recover': 'dormitory_floor_1',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                    'Fleet2Value': 39,
                    'Fleet2Record': self.now - timedelta(hours=12),
                    'Fleet2Recover': 'dormitory_floor_2',
                    'Fleet2Oath': False,
                    'Fleet2Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)
        emotion = new['Main']['Emotion']

        self.assertEqual(emotion['Fleet1Value'], 150)
        self.assertEqual(emotion['Fleet2Value'], 150)
        self.assertEqual(emotion['Fleet1Record'], self.now)
        self.assertEqual(emotion['Fleet2Record'], self.now)

    def test_template_config_skips_emotion_recovery(self):
        old_record = self.now - timedelta(hours=12)
        old = {
            'Main': {
                'Emotion': {
                    'Fleet1Value': 119,
                    'Fleet1Record': old_record,
                    'Fleet1Recover': 'not_in_dormitory',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now, is_template=True)
        emotion = new['Main']['Emotion']

        self.assertEqual(emotion['Fleet1Value'], 119)
        self.assertEqual(emotion['Fleet1Record'], datetime(2020, 1, 1))
        self.assertNotEqual(emotion['Fleet1Record'], self.now)

    def test_equal_record_time_does_not_recover_emotion(self):
        old = {
            'Main': {
                'Emotion': {
                    'Fleet1Value': 39,
                    'Fleet1Record': self.now,
                    'Fleet1Recover': 'not_in_dormitory',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)
        emotion = new['Main']['Emotion']

        self.assertEqual(emotion['Fleet1Value'], 39)
        self.assertEqual(emotion['Fleet1Record'], self.now)

    def test_future_record_time_does_not_recover_emotion(self):
        future_record = self.now + timedelta(minutes=1)
        old = {
            'Main': {
                'Emotion': {
                    'Fleet1Value': 39,
                    'Fleet1Record': future_record,
                    'Fleet1Recover': 'not_in_dormitory',
                    'Fleet1Oath': False,
                    'Fleet1Onsen': False,
                },
            },
        }

        new = ConfigUpdater().config_update(old, now=self.now)
        emotion = new['Main']['Emotion']

        self.assertEqual(emotion['Fleet1Value'], 39)
        self.assertEqual(emotion['Fleet1Record'], future_record)


if __name__ == '__main__':
    unittest.main()
