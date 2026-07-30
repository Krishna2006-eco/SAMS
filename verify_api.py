from app import app

client = app.test_client()
for path, payload in [
    ('/api/v1/attendance/simulate', {'target_percentage': 75, 'attended': 30, 'total': 40}),
    ('/api/v1/grades/weighted-average', {'components': [{'score': 80, 'weight': 0.2}]}),
    ('/api/v1/grades/cgpa-projection', {'term_scores': [80, 82]}),
]:
    response = client.post(path, json=payload)
    print(path, response.status_code, response.get_json())
