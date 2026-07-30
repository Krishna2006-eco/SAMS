from flask import Blueprint, jsonify, request, session
from services.academic_service import AcademicService
from database import get_db_connection

api = Blueprint('api', __name__, url_prefix='/api/v1')


def api_response(success, data=None, error=None):
    return jsonify({
        'success': success,
        'data': data,
        'error': error,
    })


@api.route('/attendance/simulate', methods=['POST'])
def simulate_attendance():
    payload = request.get_json(silent=True) or {}
    target_percentage = payload.get('target_percentage', 75)
    attended = payload.get('attended', 0)
    total = payload.get('total', 0)
    return api_response(True, AcademicService.attendance_simulation(target_percentage, attended, total))


@api.route('/grades/weighted-average', methods=['POST'])
def weighted_average():
    payload = request.get_json(silent=True) or {}
    scores = payload.get('components', [])
    return api_response(True, {'weighted_average': AcademicService.calculate_weighted_average(scores)})


@api.route('/grades/cgpa-projection', methods=['POST'])
def cgpa_projection():
    payload = request.get_json(silent=True) or {}
    scores = payload.get('term_scores', [])
    return api_response(True, {'projected_cgpa': AcademicService.cgpa_projection(scores)})


@api.route('/students/me/alerts', methods=['GET'])
def student_alerts():
    if 'user_id' not in session:
        return api_response(False, None, 'Authentication required')
    conn = get_db_connection()
    student = conn.execute('SELECT id, full_name FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return api_response(True, {'student_id': student['id'], 'name': student['full_name']})
