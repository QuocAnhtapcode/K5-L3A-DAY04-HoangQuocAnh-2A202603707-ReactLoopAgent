"""Bài 4: kiểm tra nguồn và lượt sửa bằng provider giả, không gọi API."""
import unittest

from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, final, tool_call


class SourceValidationTests(unittest.TestCase):
    def test_unobserved_link_does_not_satisfy_source_check(self):
        tools = StatusTools()
        details = tools.get_incident_details('cloudflare', 'c60k3g4vsoc1')
        original = final('Nguồn: https://example.invalid/incident')
        provider = FakeProvider([
            tool_call('cf', 'get_incident_details',
                      '{"provider":"cloudflare","incident_id":"c60k3g4vsoc1"}'),
            original, final('Theo snapshot, incident monitoring. ' + details['url']),
        ])
        result = run_agent('Kiểm tra Spectrum', provider, tools, max_steps=3)
        self.assertEqual(result['status'], 'completed')
        self.assertIn(details['url'], result['answer'])
        # Giữ nguyên câu trả lời cũ, thêm feedback, rồi mới gọi model sửa.
        self.assertEqual(provider.histories[2][-2], original['message'])
        self.assertIn(details['url'], provider.histories[2][-1]['content'])
        self.assertTrue(any(e['event'] == 'validation_missing_source'
                            for e in result['trace']))

    def test_repeated_missing_source_uses_existing_model_budget(self):
        provider = FakeProvider([
            tool_call('cf', 'get_incident_details',
                      '{"provider":"cloudflare","incident_id":"c60k3g4vsoc1"}'),
            final('Thiếu nguồn lần 1'), final('Thiếu nguồn lần 2'),
        ])
        result = run_agent('Kiểm tra', provider, StatusTools(), max_steps=3)
        self.assertEqual(result['status'], 'max_steps')
        self.assertEqual(len(provider.histories), 3)
        self.assertEqual(len(result['usage']), 3)
        self.assertEqual(sum(e['event'] == 'validation_missing_source'
                             for e in result['trace']), 2)

    def test_status_only_run_does_not_require_incident_url(self):
        provider = FakeProvider([
            tool_call('gh', 'get_status', '{"provider":"github"}'),
            final('Theo snapshot, GitHub operational.'),
        ])
        result = run_agent('Kiểm tra tổng quan', provider, StatusTools())
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(e['event'] == 'validation_missing_source'
                             for e in result['trace']))


if __name__ == '__main__':
    unittest.main()
