import unittest

from am_style.synthetic import generate_projected_seeds, generate_r4_projected_seeds
from am_style.contracts import SpeechFrame
from am_style.render import gap_unit, render_canonical


class GapProducerTests(unittest.TestCase):
    def test_new_time_questions_have_new_identity_and_leave_old_frames_intact(self):
        old = generate_projected_seeds()
        new = generate_r4_projected_seeds()
        self.assertEqual(old, generate_projected_seeds())
        for before, after in zip(old, new):
            self.assertNotEqual(before['id'], after['id'])
            self.assertNotEqual(before['frame_sha256'], after['frame_sha256'])
            self.assertEqual(before['group_id'], after['group_id'])
            self.assertEqual(before['split'], after['split'])
            if after['group_id'] == 'empty-analysis-known-gap':
                text = render_canonical(SpeechFrame.freeze(after['frame']))
                self.assertIn('测试准备什么时候开始，预计需要多久？', text)
                self.assertNotIn('需要包含哪些内容', text)
                self.assertNotIn('提醒', text)

    def test_start_time_and_duration_are_distinct_from_reminder_time(self):
        start = gap_unit({'id': 'start', 'slot': 'start_time', 'object': '试验'})
        duration = gap_unit({'id': 'duration', 'slot': 'duration', 'object': '试验'})
        self.assertIn('试验准备什么时候开始？', start['variants'])
        self.assertIn('试验预计需要多久？', duration['variants'])
        self.assertNotEqual(start['variants'], duration['variants'])


if __name__ == '__main__':
    unittest.main()
