from datetime import date


class AcademicService:
    @staticmethod
    def calculate_grade(percentage):
        if percentage >= 90:
            return 'A+'
        if percentage >= 80:
            return 'A'
        if percentage >= 70:
            return 'B'
        if percentage >= 60:
            return 'C'
        if percentage >= 50:
            return 'D'
        return 'F'

    @staticmethod
    def calculate_weighted_average(component_scores):
        total_weight = sum(item['weight'] for item in component_scores)
        if total_weight <= 0:
            return 0.0
        weighted_total = sum(item['score'] * item['weight'] for item in component_scores)
        return round(weighted_total / total_weight, 2)

    @staticmethod
    def attendance_simulation(target_percentage, attended, total):
        from services.analytics_service import attendance_status
        return attendance_status(target_percentage, attended, total)

    @staticmethod
    def early_warning(attendance_percent, previous_term, current_term):
        warnings = []
        if attendance_percent < 75:
            warnings.append('Attendance below 75%')
        if previous_term and current_term and previous_term - current_term > 15:
            warnings.append('Grade drop above 15%')
        return warnings

    @staticmethod
    def cgpa_projection(term_scores):
        if not term_scores:
            return 0.0
        return round(sum(term_scores) / len(term_scores), 2)
