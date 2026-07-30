import os
import json


class SimpleAIAssistant:
    def __init__(self):
        self.api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('OPENAI_API_KEY')

    def interpret(self, query):
        lower = query.lower()
        if 'attendance' in lower and ('miss' in lower or 'improve' in lower or 'improving' in lower or 'help' in lower):
            return {
                'intent': 'SIMULATE_ATTENDANCE',
                'query': query,
                'parameters': {'target_percentage': 75}
            }
        if 'cgpa' in lower or 'gpa' in lower:
            return {
                'intent': 'CALCULATE_REQUIRED_CGPA',
                'query': query,
                'parameters': {}
            }
        return {
            'intent': 'SUMMARIZE_SYLLABUS',
            'query': query,
            'parameters': {}
        }

    def respond(self, query):
        parsed = self.interpret(query)
        return {
            'success': True,
            'data': {
                'intent': parsed['intent'],
                'message': 'AI assistant ready. Connect a provider API key for live responses.',
                'parsed': parsed,
            },
            'error': None,
        }
