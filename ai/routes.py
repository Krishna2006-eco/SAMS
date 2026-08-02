from flask import Blueprint, jsonify, request, session
from functools import wraps
from ai.assistant import StudyAssistant
from repositories.student_repository import StudentRepository

ai = Blueprint('ai', __name__, url_prefix='/api/v1/ai')
assistant = StudyAssistant()


def api_response(success, data=None, error=None):
    return jsonify({'success': success, 'data': data, 'error': error})


def login_required_api(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return api_response(False, None, 'Please log in to use the assistant.'), 401
        return f(*args, **kwargs)
    return wrapper


@ai.route('/assist', methods=['POST'])
@login_required_api
def assist():
    payload = request.get_json(silent=True) or {}
    query = payload.get('query', '')

    student_data = None
    if session.get('role') == 'student':
        repo = StudentRepository()
        try:
            student_data = repo.get_student_dashboard_data(session['user_id'])
        finally:
            repo.close()

    result = assistant.respond(query, student_data=student_data)
    return api_response(result['success'], result['data'], result['error'])
