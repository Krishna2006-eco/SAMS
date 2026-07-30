from database import get_db_connection


class AlertService:
    @staticmethod
    def generate_warnings_for_students():
        conn = get_db_connection()
        students = conn.execute("SELECT id, full_name FROM users WHERE role = 'student' AND status = 'active'").fetchall()
        warnings = []
        for student in students:
            study_rows = conn.execute(
                "SELECT COUNT(*) AS count FROM study_logs WHERE student_id = ?",
                (student['id'],)
            ).fetchone()
            pending_tasks = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE student_id = ? AND is_completed = 0",
                (student['id'],)
            ).fetchone()
            total_hours = conn.execute(
                "SELECT COALESCE(SUM(hours_spent), 0) AS total_hours FROM study_logs WHERE student_id = ?",
                (student['id'],)
            ).fetchone()

            if not study_rows or study_rows['count'] == 0:
                warnings.append({
                    'student_id': student['id'],
                    'student_name': student['full_name'],
                    'reason': 'No study activity logged recently. Encourage a study session this week.',
                    'severity': 'high',
                    'recommendation': 'Log at least one study session and review pending tasks.'
                })
            elif pending_tasks and pending_tasks['count'] >= 3:
                warnings.append({
                    'student_id': student['id'],
                    'student_name': student['full_name'],
                    'reason': f'{pending_tasks["count"]} pending tasks are still open.',
                    'severity': 'medium',
                    'recommendation': 'Help the student prioritize submissions and study planning.'
                })
            elif total_hours and total_hours['total_hours'] < 5:
                warnings.append({
                    'student_id': student['id'],
                    'student_name': student['full_name'],
                    'reason': 'Study hours are below the expected weekly target.',
                    'severity': 'medium',
                    'recommendation': 'Encourage a consistent weekly study routine.'
                })
            else:
                warnings.append({
                    'student_id': student['id'],
                    'student_name': student['full_name'],
                    'reason': 'Monitoring active. Student is keeping pace.',
                    'severity': 'low',
                    'recommendation': 'Continue supporting current momentum.'
                })
        conn.close()
        return warnings
