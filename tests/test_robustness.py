"""Bài 2: kiểm tra lỗi đi qua toàn bộ loop, không gọi API thật."""
import json
import unittest
from unittest.mock import Mock

from test_lab import FakeProvider, final, tool_call
from agent import run_agent
from status_tools import StatusTools


class RobustnessTests(unittest.TestCase):
    def test_invalid_budget_does_not_call_provider(self):
        for budget in (0, -1, True, 1.5, None):
            with self.subTest(budget=budget):
                provider = Mock()
                result = run_agent('Kiểm tra', provider, StatusTools(), budget)
                self.assertEqual(result['status'], 'error')
                provider.complete.assert_not_called()

    def test_invalid_arguments_return_to_model_without_executing_tool(self):
        for arguments in ('{', '[]', 'null', '"github"', '1', None):
            with self.subTest(arguments=arguments):
                tools = Mock()
                provider = FakeProvider([
                    tool_call('bad', 'get_status', arguments), final('Thiếu dữ liệu'),
                ])
                result = run_agent('Kiểm tra', provider, tools)
                observation = provider.histories[1][-1]
                self.assertEqual(observation['tool_call_id'], 'bad')
                self.assertEqual(json.loads(observation['content'])['error'],
                                 'INVALID_ARGUMENTS')
                tools.execute.assert_not_called()
                self.assertEqual(result['status'], 'completed')

    def test_registry_errors_are_observations_in_history_and_trace(self):
        cases = [
            ('missing', '{}', StatusTools(), 'UNKNOWN_TOOL'),
            ('get_status', '{"provider":"invalid"}', StatusTools(), 'ValueError'),
            ('get_status', '{"provider":"github"}', StatusTools(fail=True),
             'TimeoutError'),
        ]
        for name, arguments, tools, error in cases:
            with self.subTest(error=error):
                provider = FakeProvider([tool_call('failed', name, arguments),
                                         final('Không xác nhận được trạng thái')])
                result = run_agent('Kiểm tra', provider, tools)
                observation = json.loads(provider.histories[1][-1]['content'])
                self.assertEqual(observation['error'], error)
                event = next(e for e in result['trace'] if e['event'] == 'tool')
                self.assertEqual(event['result'], observation)
                self.assertEqual(result['status'], 'completed')

    def test_tool_exception_does_not_skip_other_calls(self):
        response = tool_call('cf', 'get_status', '{"provider":"cloudflare"}')
        second = tool_call('gh', 'get_status', '{"provider":"github"}')
        response['calls'] += second['calls']
        response['message']['tool_calls'] += second['message']['tool_calls']
        tools = Mock()
        tools.execute.side_effect = [TimeoutError('timeout'), {'provider': 'github'}]
        provider = FakeProvider([response, final('Chỉ kiểm tra được GitHub')])
        result = run_agent('Kiểm tra hai bên', provider, tools)
        observations = provider.histories[1][-2:]
        self.assertEqual([m['tool_call_id'] for m in observations], ['cf', 'gh'])
        self.assertEqual(json.loads(observations[0]['content'])['error'], 'TimeoutError')
        self.assertEqual(json.loads(observations[1]['content'])['provider'], 'github')
        self.assertEqual(result['status'], 'completed')

    def test_provider_failure_after_tool_preserves_evidence_and_usage(self):
        first = tool_call('gh', 'get_status', '{"provider":"github"}')
        first['usage'] = {'total_tokens': 12}
        provider = Mock()
        provider.complete.side_effect = [first, RuntimeError('private-request-data')]
        result = run_agent('Kiểm tra', provider, StatusTools())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['usage'], [{'total_tokens': 12}])
        self.assertTrue(any(e['event'] == 'tool' for e in result['trace']))
        self.assertEqual(result['trace'][-1]['event'], 'provider_error')
        self.assertNotIn('private-request-data', json.dumps(result))

    def test_malformed_provider_response_returns_error(self):
        for response in (None, {}, dict(final(), message=None)):
            with self.subTest(response=response):
                result = run_agent('Kiểm tra', FakeProvider([response]), StatusTools())
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['trace'][-1]['event'], 'provider_error')

    def test_abnormal_finish_does_not_execute_partial_tool_calls(self):
        for finish in ('length', 'content_filter', None):
            with self.subTest(finish=finish):
                response = tool_call('gh', 'get_status', '{"provider":"github"}')
                response['finish'] = finish
                tools = Mock()
                result = run_agent('Kiểm tra', FakeProvider([response]), tools)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['trace'][-1]['finish'], finish)
                tools.execute.assert_not_called()

    def test_repeated_calls_stop_at_model_budget(self):
        responses = [tool_call(str(i), 'get_status', '{"provider":"github"}')
                     for i in range(3)]
        provider = FakeProvider(responses)
        result = run_agent('Kiểm tra', provider, StatusTools(), max_steps=3)
        self.assertEqual(result['status'], 'max_steps')
        self.assertEqual(len(provider.histories), 3)
        self.assertEqual(len(result['usage']), 3)
        self.assertTrue(all('event' in event for event in result['trace']))
        self.assertEqual(result['trace'][-1]['event'], 'max_steps')


if __name__ == '__main__':
    unittest.main()
