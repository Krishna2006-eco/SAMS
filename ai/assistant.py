import os
import requests

# Google AI Studio / Gemini Developer API.
# Get a free key at https://aistudio.google.com/apikey
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')  # free-tier eligible


class StudyAssistant:
    """
    Calls the Gemini API to answer a student's question, grounded in their
    real study data (recent sessions, weekly hours, tasks, streak) so the
    advice is specific to them rather than generic.
    """

    def __init__(self):
        self.api_key = os.environ.get('GEMINI_API_KEY')

    def _build_context_summary(self, student_data):
        if not student_data:
            return "No study data is available for this student yet."

        lines = []
        lines.append(f"Weekly study hours: {student_data.get('weekly_hours') or 0}")
        lines.append(
            f"Tasks: {student_data.get('completed_tasks', 0)} completed out of "
            f"{student_data.get('total_tasks', 0)} total"
        )

        study_summary = student_data.get('study_summary') or []
        if study_summary:
            subject_lines = [
                f"  - {row['subject_name']}: {row['total_hours']} hrs total"
                for row in study_summary
            ]
            lines.append("Study hours by subject:\n" + "\n".join(subject_lines))

        tasks = student_data.get('tasks') or []
        pending = [t for t in tasks if not t['is_completed']]
        if pending:
            task_lines = [
                f"  - {t['title']}" + (f" (due {t['due_date']})" if t['due_date'] else "")
                for t in pending[:5]
            ]
            lines.append("Pending tasks:\n" + "\n".join(task_lines))

        return "\n".join(lines)

    def respond(self, query, student_data=None):
        if not self.api_key:
            return {
                'success': False,
                'data': None,
                'error': 'AI assistant is not configured yet. Ask your admin to set the '
                         'GEMINI_API_KEY environment variable.',
            }

        if not query or not query.strip():
            return {'success': False, 'data': None, 'error': 'Please enter a question.'}

        context_summary = self._build_context_summary(student_data)

        system_prompt = (
            "You are a supportive study assistant inside a student academic tracking app called SAMS. "
            "Answer the student's question briefly (2-4 sentences, plain language, no markdown headers). "
            "Use the student's real data below when it's relevant to give specific, encouraging, "
            "actionable advice. Never invent grades or numbers that aren't in the data provided.\n\n"
            f"Student's current data:\n{context_summary}"
        )

        url = GEMINI_API_URL.format(model=GEMINI_MODEL)

        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": query.strip()}]}],
                    "generationConfig": {"maxOutputTokens": 300},
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()

            candidates = payload.get("candidates") or []
            if not candidates:
                return {'success': False, 'data': None, 'error': 'The assistant could not generate a response.'}

            parts = candidates[0].get("content", {}).get("parts", [])
            message = "".join(p.get("text", "") for p in parts).strip()
            message = message or "I couldn't generate a response. Try rephrasing."

            return {
                'success': True,
                'data': {'message': message},
                'error': None,
            }

        except requests.exceptions.Timeout:
            return {'success': False, 'data': None, 'error': 'The assistant took too long to respond. Try again.'}
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (400, 401, 403):
                err = 'AI assistant API key is invalid or missing permissions. Ask your admin to check it.'
            elif status == 429:
                err = 'The assistant hit its free-tier rate limit. Please try again in a minute.'
            else:
                err = 'The assistant is temporarily unavailable.'
            return {'success': False, 'data': None, 'error': err}
        except Exception:
            return {'success': False, 'data': None, 'error': 'The assistant is temporarily unavailable.'}
