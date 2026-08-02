import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ai.assistant import StudyAssistant


def test_assistant_returns_clear_error_when_no_api_key_configured():
    with patch.dict(os.environ, {}, clear=True):
        assistant = StudyAssistant()
        response = assistant.respond('help me improve my attendance')
        assert response['success'] is False
        assert 'GEMINI_API_KEY' in response['error']


def test_assistant_rejects_empty_query():
    with patch.dict(os.environ, {'GEMINI_API_KEY': 'fake-key-for-test'}):
        assistant = StudyAssistant()
        response = assistant.respond('   ')
        assert response['success'] is False
        assert 'question' in response['error'].lower()
