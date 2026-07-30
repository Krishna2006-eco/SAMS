import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services import alert_service


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if "FROM users" in query:
            return FakeCursor([{'id': 1, 'full_name': 'Ada'}])
        if "SUM(hours_spent)" in query:
            return FakeCursor([{'total_hours': 0.0}])
        if "COUNT(*) AS count" in query and "study_logs" in query:
            return FakeCursor([{'count': 0}])
        if "tasks" in query and "is_completed=0" in query:
            return FakeCursor([{'count': 4}])
        return FakeCursor([])

    def close(self):
        return None


def test_generate_warnings_flags_students_with_no_recent_activity(monkeypatch):
    monkeypatch.setattr(alert_service, 'get_db_connection', lambda: FakeConnection())

    warnings = alert_service.AlertService.generate_warnings_for_students()

    assert len(warnings) == 1
    assert warnings[0]['student_name'] == 'Ada'
    assert warnings[0]['severity'] == 'high'
    assert 'study activity' in warnings[0]['reason'].lower()
