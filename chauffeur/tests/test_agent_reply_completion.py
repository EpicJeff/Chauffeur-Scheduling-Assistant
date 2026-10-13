"""Calendar replies must survive repeated tool calls and finish honestly."""
import unittest
import io
import json
from unittest.mock import patch
from harness import storage
from services import agent_router
from services.llm import _call_llm_json

CALL = {'name': 'get_calendar_events',
        'arguments': {'start_date': '2026-10-13', 'end_date': '2026-10-13'}}
ANSWER = 'Soccer practice at Community field, 4 PM to 5 PM.'
EVENTS = {'status': 'success', 'events': [{'id': 'soccer', 'title': 'Soccer practice',
           'start': '2026-10-13T16:00:00-04:00', 'end': '2026-10-13T17:00:00-04:00',
           'location': 'Community field'}]}


class CompletionTests(unittest.TestCase):
    def test_gemini_agent_instructions_are_separate_from_the_user_request(self):
        payloads = []
        def provider(request, **kwargs):
            payloads.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'candidates': [{'content': {'parts': [
                {'text': json.dumps({'message': ANSWER})}]}}]}).encode())
        with patch('services.llm_budget.urlopen', provider):
            for model in ('gemini-2.5-flash-lite', 'gemma-slow'):
                _call_llm_json('gemini', '', 'offline', model, 'Known identity and date',
                               'Calendar today', use_system_instruction=True)
        self.assertEqual(payloads[0]['systemInstruction']['parts'][0]['text'], 'Known identity and date')
        self.assertEqual(payloads[0]['contents'][0]['parts'][0]['text'], 'Calendar today')
        self.assertNotIn('systemInstruction', payloads[1])
        self.assertIn('Known identity and date', payloads[1]['contents'][0]['parts'][0]['text'])

    def test_answer_with_repeated_calendar_lookup_is_kept(self):
        responses = [{'message': 'Fetching your schedule.', 'tool_calls': [CALL]},
                     {'message': ANSWER, 'tool_calls': [CALL]}]
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=responses * 2) as model, \
                patch.object(agent_router, 'get_calendar_events', return_value=EVENTS) as calendar:
            result = agent_router.process_agent_request("What's my schedule like today?", source='family')
        self.assertEqual(result['message'], ANSWER)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(calendar.call_count, 1)
        self.assertEqual(model.call_count, 2)

    def test_repeated_lookup_without_answer_is_never_reported_as_success(self):
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'tool_calls': [CALL]}), \
                patch.object(agent_router, 'get_calendar_events', return_value=EVENTS) as calendar:
            result = agent_router.process_agent_request('Calendar please', source='family')
        self.assertEqual(calendar.call_count, 1)
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('processed your request', result['message'])

    def test_blank_model_reply_is_never_reported_as_success(self):
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={}):
            result = agent_router.process_agent_request('Calendar please', source='family')
        self.assertEqual(result['status'], 'error')

    def test_new_lookup_still_executes_before_final_answer(self):
        later = {'name': 'get_calendar_events',
                 'arguments': {'start_date': '2026-10-14', 'end_date': '2026-10-14'}}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=[
                {'tool_calls': [CALL]}, {'tool_calls': [later]}, {'message': ANSWER}]), \
                patch.object(agent_router, 'get_calendar_events', return_value=EVENTS) as calendar:
            result = agent_router.process_agent_request('Compare today and tomorrow', source='family')
        self.assertEqual(calendar.call_count, 2)
        self.assertEqual(result['message'], ANSWER)

    def test_results_and_followup_are_sent_as_conversation_data(self):
        seen = []
        def model(prompt, tools, system):
            seen.append((prompt, system))
            return {'tool_calls': [CALL]} if len(seen) == 1 else {'message': ANSWER}
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=model), \
                patch.object(agent_router, 'get_calendar_events', return_value=EVENTS):
            agent_router.process_agent_request('Today.', source='family', history=[
                {'role': 'user', 'content': "What's my schedule like?"},
                {'role': 'assistant', 'content': 'What date are you interested in?'}])
        self.assertIn("What's my schedule like?", seen[0][0])
        self.assertIn('CURRENT USER REQUEST: Today.', seen[0][0])
        self.assertNotIn('What date are you interested in?', seen[0][1])
        self.assertIn('Community field', seen[1][0])
        self.assertNotIn('Community field', seen[1][1])

    def test_failed_lookup_cannot_be_closed_as_a_successful_answer(self):
        with patch.object(agent_router, 'call_gemma_with_fallback', return_value={'tool_calls': [CALL]}), \
                patch.object(agent_router, 'get_calendar_events', return_value={'status': 'error', 'message': 'Bad dates'}):
            result = agent_router.process_agent_request('Calendar please', source='family')
        self.assertEqual(result['status'], 'error')

    def test_completed_lookup_is_not_a_pending_clarification(self):
        with patch.object(agent_router, 'call_gemma_with_fallback', side_effect=[
                {'tool_calls': [CALL]}, {'message': ANSWER + ' Anything else?', 'tool_calls': [CALL]}]), \
                patch.object(agent_router, 'get_calendar_events', return_value=EVENTS):
            result = agent_router.process_agent_request('Calendar please', source='family')
        self.assertFalse(result['needs_clarification'])


if __name__ == '__main__':
    unittest.main()
