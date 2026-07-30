from datetime import date, timedelta


def calculate_streak(study_dates):
    """Count consecutive study days ending today."""
    if not study_dates:
        return 0
    study_dates = sorted(set(study_dates), reverse=True)
    today = date.today()
    if study_dates[0] != today:
        return 0
    streak = 1
    for index in range(1, len(study_dates)):
        expected = today - timedelta(days=streak)
        if study_dates[index] == expected:
            streak += 1
        else:
            break
    return streak


def calculate_attendance_percentage(attended, total):
    if total <= 0:
        return 0.0
    return round((attended / total) * 100, 2)


def attendance_status(target_percentage, attended, total):
    current = calculate_attendance_percentage(attended, total)
    if current >= target_percentage:
        return {
            'status': 'safe_to_miss_classes',
            'current_percentage': current,
            'message': 'You are currently safe to miss classes.'
        }
    classes_needed = (target_percentage * total - attended * 100) / 100
    return {
        'status': 'classes_needed_to_reach_cutoff',
        'current_percentage': current,
        'classes_needed': max(0, round(classes_needed, 2)),
        'message': 'You need more classes to reach the target attendance.'
    }


def estimate_cgpa(scores):
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 2)
