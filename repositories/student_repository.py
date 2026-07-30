from database import get_db_connection


class StudentRepository:
    def __init__(self, conn=None):
        self.conn = conn or get_db_connection()

    def get_student_dashboard_data(self, student_id):
        study_logs = self.conn.execute('''
            SELECT sl.*, s.name as subject_name
            FROM study_logs sl
            JOIN subjects s ON sl.subject_id = s.id
            WHERE sl.student_id = ?
            ORDER BY sl.study_date DESC
            LIMIT 10
        ''', (student_id,)).fetchall()

        study_summary = self.conn.execute('''
            SELECT s.name as subject_name, SUM(sl.hours_spent) as total_hours
            FROM study_logs sl
            JOIN subjects s ON sl.subject_id = s.id
            WHERE sl.student_id = ?
            GROUP BY s.id
            ORDER BY total_hours DESC
        ''', (student_id,)).fetchall()

        tasks = self.conn.execute('''
            SELECT t.*, u.full_name as teacher_name
            FROM tasks t
            JOIN users u ON t.teacher_id = u.id
            WHERE t.student_id = ?
            ORDER BY t.is_completed ASC, t.due_date ASC
        ''', (student_id,)).fetchall()

        streak_rows = self.conn.execute('''
            SELECT DISTINCT study_date
            FROM study_logs
            WHERE student_id = ?
            ORDER BY study_date DESC
        ''', (student_id,)).fetchall()

        weekly_hours = self.conn.execute('''
            SELECT SUM(hours_spent) as total_hours
            FROM study_logs
            WHERE student_id = ? AND study_date >= date('now', '-6 days')
        ''', (student_id,)).fetchone()

        completed_tasks = self.conn.execute('''
            SELECT COUNT(*) as count
            FROM tasks
            WHERE student_id = ? AND is_completed = 1
        ''', (student_id,)).fetchone()

        total_tasks = self.conn.execute('''
            SELECT COUNT(*) as count
            FROM tasks
            WHERE student_id = ?
        ''', (student_id,)).fetchone()

        return {
            'study_logs': study_logs,
            'study_summary': study_summary,
            'tasks': tasks,
            'streak_rows': streak_rows,
            'weekly_hours': weekly_hours['total_hours'] if weekly_hours else 0,
            'completed_tasks': completed_tasks['count'] if completed_tasks else 0,
            'total_tasks': total_tasks['count'] if total_tasks else 0,
        }

    def close(self):
        self.conn.close()
