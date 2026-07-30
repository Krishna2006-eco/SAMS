import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ai.assistant import SimpleAIAssistant


def test_assistant_returns_default_structure_for_unknown_query():
    assistant = SimpleAIAssistant()
    response = assistant.respond('hello there')
    assert response['success'] is True
    assert response['data']['intent'] == 'SUMMARIZE_SYLLABUS'


def test_assistant_detects_attendance_query():
    assistant = SimpleAIAssistant()
    response = assistant.respond('help me improve my attendance')
    assert response['data']['intent'] == 'SIMULATE_ATTENDANCE'
