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


if __name__ == '__main__':
    unittest.main()
