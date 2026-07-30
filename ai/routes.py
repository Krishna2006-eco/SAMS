from flask import Blueprint, jsonify, request
from ai.assistant import SimpleAIAssistant

ai = Blueprint('ai', __name__, url_prefix='/api/v1/ai')
assistant = SimpleAIAssistant()


def api_response(success, data=None, error=None):
    return jsonify({'success': success, 'data': data, 'error': error})


@ai.route('/assist', methods=['POST'])
def assist():
    payload = request.get_json(silent=True) or {}
    query = payload.get('query', '')
    return api_response(True, assistant.respond(query))
