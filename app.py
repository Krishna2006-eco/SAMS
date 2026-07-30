import os
import secrets
import sys
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import CSRFProtect

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if load_dotenv:
    load_dotenv(BASE_DIR / '.env')

from database import get_db_connection, init_db
from services.analytics_service import calculate_streak
from repositories.student_repository import StudentRepository
from services.alert_service import AlertService
from api.routes import api
from ai.routes import ai

app = Flask(__name__)
# Secret key comes from the environment. If not set, a random one is generated
# each start (safe, but it logs everyone out on restart - so set SECRET_KEY in production).
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['DEBUG'] = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')
app.register_blueprint(api)
app.register_blueprint(ai)

# Protects every POST form against CSRF attacks
csrf = CSRFProtect(app)

# Initialize the database when the app starts
init_db()

# ----- Helper Functions -----

def login_required(f):
    """Decorator to require login for certain pages."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    """Decorator to require teacher role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'teacher':
            flash('This page is for teachers only.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    """Decorator to require student role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'student':
            flash('This page is for students only.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Access denied', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


class CurrentUser:
    def __init__(self, session):
        self.id = session.get('user_id')
        self.theme = session.get('theme', 'light')
        self.username = session.get('username')
        self.full_name = session.get('full_name')

    @property
    def is_authenticated(self):
        return bool(self.id)


@app.context_processor
def inject_current_user():
    return {'current_user': CurrentUser(session)}


def calculate_grade(percentage):
    """Convert percentage to letter grade."""
    if percentage >= 90:
        return 'A+'
    elif percentage >= 80:
        return 'A'
    elif percentage >= 70:
        return 'B'
    elif percentage >= 60:
        return 'C'
    elif percentage >= 50:
        return 'D'
    else:
        return 'F'


def notify(conn, user_id, message, link=None):
    """Create an in-app notification for a user."""
    conn.execute(
        'INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)',
        (user_id, message, link)
    )


def compute_streak(conn, student_id):
    """Count consecutive study days ending today for a student."""
    rows = conn.execute('''
        SELECT DISTINCT study_date FROM study_logs
        WHERE student_id = ? ORDER BY study_date DESC
    ''', (student_id,)).fetchall()
    streak = 0
    if rows:
        study_dates = [datetime.fromisoformat(r['study_date']).date() for r in rows]
        today = date.today()
        if study_dates[0] == today:
            streak = 1
            for next_date in study_dates[1:]:
                if next_date == today - timedelta(days=streak):
                    streak += 1
                else:
                    break
    return streak


def streak_badge(streak):
    """Return a fun badge for a streak length."""
    if streak >= 30:
        return ('🏆', 'Legend')
    elif streak >= 14:
        return ('🔥', 'On Fire')
    elif streak >= 7:
        return ('⚡', 'Consistent')
    elif streak >= 3:
        return ('🌱', 'Building')
    return ('', '')


@app.context_processor
def inject_unread_notifications():
    """Make the unread notification count available in the navbar on every page."""
    count = 0
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            row = conn.execute(
                'SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0',
                (session['user_id'],)
            ).fetchone()
            conn.close()
            count = row['c'] if row else 0
        except Exception:
            count = 0
    return {'unread_count': count}

# ----- Routes -----

@app.route('/')
def home():
    """Home page."""
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handle user registration."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        full_name = request.form['full_name']
        
        if role not in ('student', 'teacher'):
            flash('Invalid role selected.', 'error')
            return redirect(url_for('register'))

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(url_for('register'))

        conn = get_db_connection()
        
        # Check if username already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ?', (username,)
        ).fetchone()
        
        if existing_user:
            flash('Username already exists. Please choose another.', 'error')
            conn.close()
            return redirect(url_for('register'))
        
        # Insert new user with pending approval and default theme.
        # The password is HASHED - we never store the real password.
        conn.execute(
            'INSERT INTO users (username, password, role, full_name, status, theme) VALUES (?, ?, ?, ?, ?, ?)',
            (username, generate_password_hash(password), role, full_name, 'pending', 'light')
        )
        conn.commit()
        conn.close()
        
        flash('Your account is pending admin approval.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()

        password_ok = False
        if user:
            stored = user['password']
            if stored.startswith(('pbkdf2:', 'scrypt:')):
                # Normal case: stored password is a secure hash
                password_ok = check_password_hash(stored, password)
            else:
                # Old account created before hashing existed.
                # If the plain password matches, upgrade it to a hash automatically.
                if stored == password:
                    password_ok = True
                    conn.execute(
                        'UPDATE users SET password = ? WHERE id = ?',
                        (generate_password_hash(password), user['id'])
                    )
                    conn.commit()
        conn.close()

        if user and password_ok:
            if user['status'] == 'pending':
                flash('Your account is awaiting admin approval.', 'error')
                return redirect(url_for('login'))
            if user['status'] == 'blocked':
                flash('Your account has been suspended. Contact admin.', 'error')
                return redirect(url_for('login'))

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            session['theme'] = user['theme'] if 'theme' in user.keys() and user['theme'] else 'light'
            
            flash(f'Welcome back, {user["full_name"]}!', 'success')
            
            if user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            else:
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    users = conn.execute('''
        SELECT * FROM users
        ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END, full_name
    ''').fetchall()
    conn.close()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_approve(user_id):
    if user_id == session['user_id']:
        flash('Admins cannot modify their own account.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    conn.execute('UPDATE users SET status = ? WHERE id = ?', ('active', user_id))
    conn.commit()
    conn.close()
    flash(f"{user['full_name']} is now active.", 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/block/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_block(user_id):
    if user_id == session['user_id']:
        flash('Admins cannot modify their own account.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    conn.execute('UPDATE users SET status = ? WHERE id = ?', ('blocked', user_id))
    conn.commit()
    conn.close()
    flash(f"{user['full_name']} has been suspended.", 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/set_role/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_set_role(user_id):
    if user_id == session['user_id']:
        flash('Admins cannot modify their own account.', 'error')
        return redirect(url_for('admin_dashboard'))

    role = request.form.get('role')
    if role not in ('student', 'teacher'):
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if user['role'] != role:
        conn.execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
        conn.commit()
        flash(f"{user['full_name']}'s role updated to {role}.", 'success')
    else:
        flash('No role changes were made.', 'success')

    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    if user_id == session['user_id']:
        flash('Admins cannot modify their own account.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if not user:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '').strip()

        if not username:
            flash('Username cannot be empty.', 'error')
            conn.close()
            return render_template('edit_user.html', user=user)

        if not full_name:
            flash('Full name cannot be empty.', 'error')
            conn.close()
            return render_template('edit_user.html', user=user)

        if username != user['username']:
            existing = conn.execute(
                'SELECT id FROM users WHERE username = ? AND id != ?',
                (username, user_id)
            ).fetchone()
            if existing:
                flash('Username already exists. Please choose another.', 'error')
                conn.close()
                return render_template('edit_user.html', user=user)

        try:
            if password:
                if len(password) < 8:
                    flash('Password must be at least 8 characters long.', 'error')
                    conn.close()
                    return render_template('edit_user.html', user=user)
                conn.execute(
                    'UPDATE users SET username = ?, full_name = ?, password = ? WHERE id = ?',
                    (username, full_name, generate_password_hash(password), user_id)
                )
                flash(f"User updated successfully. Password changed.", 'success')
            else:
                conn.execute(
                    'UPDATE users SET username = ?, full_name = ? WHERE id = ?',
                    (username, full_name, user_id)
                )
                flash(f"User updated successfully.", 'success')

            conn.commit()
            conn.close()
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            flash(f'Error updating user: {str(e)}', 'error')
            conn.close()
            return render_template('edit_user.html', user=user)

    conn.close()
    return render_template('edit_user.html', user=user)

@app.route('/logout')
def logout():
    """Log out the user."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    current_theme = session.get('theme', 'light')
    new_theme = 'dark' if current_theme == 'light' else 'light'
    conn = get_db_connection()
    conn.execute('UPDATE users SET theme = ? WHERE id = ?', (new_theme, session['user_id']))
    conn.commit()
    conn.close()
    session['theme'] = new_theme
    return redirect(request.referrer or url_for('home'))

# ----- Student Routes -----

@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    """Student's main dashboard."""
    repo = StudentRepository()
    data = repo.get_student_dashboard_data(session['user_id'])
    repo.close()

    study_dates = [datetime.fromisoformat(row['study_date']).date() for row in data['streak_rows']]
    streak = calculate_streak(study_dates)

    weekly_hours = data.get('weekly_hours', 0)
    completion_rate = 0
    if data.get('total_tasks', 0):
        completion_rate = round((data.get('completed_tasks', 0) / data['total_tasks']) * 100, 1)

    return render_template('student_dashboard.html',
                         study_logs=data['study_logs'],
                         study_summary=data['study_summary'],
                         tasks=data['tasks'],
                         streak=streak,
                         weekly_hours=weekly_hours,
                         completion_rate=completion_rate,
                         completed_tasks=data.get('completed_tasks', 0),
                         total_tasks=data.get('total_tasks', 0))

@app.route('/student/add-study-log', methods=['GET', 'POST'])
@login_required
@student_required
def add_study_log():
    """Add a new study log entry."""
    conn = get_db_connection()
    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    
    if request.method == 'POST':
        subject_id = request.form['subject_id']
        hours_spent = float(request.form['hours_spent'])
        study_date = request.form['study_date']
        notes = request.form.get('notes', '')
        
        conn.execute('''
            INSERT INTO study_logs (student_id, subject_id, hours_spent, study_date, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (session['user_id'], subject_id, hours_spent, study_date, notes))
        conn.commit()
        conn.close()
        
        flash('Study session logged successfully!', 'success')
        return redirect(url_for('student_dashboard'))
    
    conn.close()
    return render_template('add_study_log.html', subjects=subjects)

@app.route('/admin/alerts')
@login_required
@admin_required
def admin_alerts():
    alerts = AlertService.generate_warnings_for_students()
    return render_template('admin_alerts.html', alerts=alerts)

@app.route('/student/results')
@login_required
@student_required
def view_results():
    """View exam summaries and grades."""
    conn = get_db_connection()

    marks = conn.execute('''
        SELECT m.*, s.name as subject_name, u.full_name as teacher_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        JOIN users u ON m.entered_by = u.id
        WHERE m.student_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()

    exam_rows = conn.execute('''
        SELECT m.exam_name,
               COUNT(*) AS subject_count,
               SUM(m.marks_obtained) AS total_obtained,
               SUM(m.max_marks) AS total_max,
               MAX(m.created_at) AS last_entered
        FROM marks m
        WHERE m.student_id = ?
        GROUP BY m.exam_name
        ORDER BY last_entered DESC
    ''', (session['user_id'],)).fetchall()

    exam_list = []
    for exam in exam_rows:
        percentage = (exam['total_obtained'] / exam['total_max']) * 100 if exam['total_max'] else 0
        exam_list.append({
            'exam_name': exam['exam_name'],
            'subject_count': exam['subject_count'],
            'total_obtained': exam['total_obtained'],
            'total_max': exam['total_max'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'last_entered': exam['last_entered']
        })

    end_semester_marks = [mark for mark in marks if mark['exam_name'] == 'End Semester Examination']
    total_obtained = sum(mark['marks_obtained'] for mark in end_semester_marks) if end_semester_marks else 0
    total_max = sum(mark['max_marks'] for mark in end_semester_marks) if end_semester_marks else 0
    overall_percentage = (total_obtained / total_max) * 100 if total_max > 0 else 0
    overall_grade = calculate_grade(overall_percentage) if end_semester_marks else 'N/A'

    rank_info = None
    if end_semester_marks:
        all_students = conn.execute('''
            SELECT m.student_id, SUM(m.marks_obtained) as total
            FROM marks m
            WHERE m.exam_name = 'End Semester Examination'
            GROUP BY m.student_id
            ORDER BY total DESC
        ''').fetchall()

        for i, student in enumerate(all_students, 1):
            if student['student_id'] == session['user_id']:
                rank_info = {'rank': i, 'total_students': len(all_students), 'exam_name': 'End Semester Examination'}
                break

    conn.close()

    # Prepare marks trend for common exams in a fixed order
    trend_labels = ['Class Test 01', 'Class Test 02', 'Internal Examination', 'End Semester Examination']
    exam_pct_map = {e['exam_name']: e['percentage'] for e in exam_list}
    marks_trend = [exam_pct_map.get(label) for label in trend_labels]

    return render_template('view_results.html',
                         exam_list=exam_list,
                         selected_exam=None,
                         exam_results=[],
                         total_obtained=total_obtained,
                         total_max=total_max,
                         overall_percentage=round(overall_percentage, 2),
                         overall_grade=overall_grade,
                         rank_info=rank_info,
                         trend_labels=trend_labels,
                         marks_trend=marks_trend)


@app.route('/student/results/exam/<exam_name>')
@login_required
@student_required
def view_results_exam(exam_name):
    """View detailed subject results for a selected exam."""
    conn = get_db_connection()

    marks = conn.execute('''
        SELECT m.*, s.name as subject_name, u.full_name as teacher_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        JOIN users u ON m.entered_by = u.id
        WHERE m.student_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()

    exam_rows = conn.execute('''
        SELECT m.exam_name,
               COUNT(*) AS subject_count,
               SUM(m.marks_obtained) AS total_obtained,
               SUM(m.max_marks) AS total_max,
               MAX(m.created_at) AS last_entered
        FROM marks m
        WHERE m.student_id = ?
        GROUP BY m.exam_name
        ORDER BY last_entered DESC
    ''', (session['user_id'],)).fetchall()

    exam_list = []
    for exam in exam_rows:
        percentage = (exam['total_obtained'] / exam['total_max']) * 100 if exam['total_max'] else 0
        exam_list.append({
            'exam_name': exam['exam_name'],
            'subject_count': exam['subject_count'],
            'total_obtained': exam['total_obtained'],
            'total_max': exam['total_max'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'last_entered': exam['last_entered']
        })

    exam_marks = conn.execute('''
        SELECT m.*, s.name as subject_name, u.full_name as teacher_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        JOIN users u ON m.entered_by = u.id
        WHERE m.student_id = ? AND m.exam_name = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'], exam_name)).fetchall()

    exam_results = []
    for mark in exam_marks:
        percentage = (mark['marks_obtained'] / mark['max_marks']) * 100 if mark['max_marks'] else 0
        exam_results.append({
            'subject_name': mark['subject_name'],
            'exam_name': mark['exam_name'],
            'marks_obtained': mark['marks_obtained'],
            'max_marks': mark['max_marks'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'teacher_name': mark['teacher_name']
        })

    total_obtained = sum(mark['marks_obtained'] for mark in marks) if marks else 0
    total_max = sum(mark['max_marks'] for mark in marks) if marks else 0
    overall_percentage = (total_obtained / total_max) * 100 if total_max > 0 else 0
    overall_grade = calculate_grade(overall_percentage) if marks else 'N/A'

    rank_info = None
    if marks:
        latest_exam = marks[0]['exam_name']
        all_students = conn.execute('''
            SELECT m.student_id, SUM(m.marks_obtained) as total
            FROM marks m
            WHERE m.exam_name = ?
            GROUP BY m.student_id
            ORDER BY total DESC
        ''', (latest_exam,)).fetchall()

        for i, student in enumerate(all_students, 1):
            if student['student_id'] == session['user_id']:
                rank_info = {'rank': i, 'total_students': len(all_students), 'exam_name': latest_exam}
                break

    conn.close()

    # Prepare marks trend for common exams in a fixed order
    trend_labels = ['Class Test 01', 'Class Test 02', 'Internal Examination', 'End Semester Examination']
    exam_pct_map = {e['exam_name']: e['percentage'] for e in exam_list}
    marks_trend = [exam_pct_map.get(label) for label in trend_labels]

    return render_template('view_results.html',
                         exam_list=exam_list,
                         selected_exam=exam_name,
                         exam_results=exam_results,
                         total_obtained=total_obtained,
                         total_max=total_max,
                         overall_percentage=round(overall_percentage, 2),
                         overall_grade=overall_grade,
                         rank_info=rank_info,
                         trend_labels=trend_labels,
                         marks_trend=marks_trend)


@app.route('/student/complete-task/<int:task_id>')
@login_required
@student_required
def complete_task(task_id):
    """Mark a task as completed."""
    conn = get_db_connection()
    conn.execute('''
        UPDATE tasks SET is_completed = 1
        WHERE id = ? AND student_id = ?
    ''', (task_id, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Task marked as completed!', 'success')
    return redirect(url_for('student_dashboard'))

@app.route('/student/edit-study-log/<int:log_id>', methods=['GET', 'POST'])
@login_required
@student_required
def edit_study_log(log_id):
    """Edit an existing study log."""
    conn = get_db_connection()
    log = conn.execute('''
        SELECT sl.*, s.name as subject_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.id = ? AND sl.student_id = ?
    ''', (log_id, session['user_id'])).fetchone()

    if not log:
        flash('Study log not found or you do not have permission to edit it.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()

    if request.method == 'POST':
        subject_id = request.form['subject_id']
        hours_spent = float(request.form['hours_spent'])
        study_date = request.form['study_date']
        notes = request.form.get('notes', '')

        conn.execute('''
            UPDATE study_logs
            SET subject_id = ?, hours_spent = ?, study_date = ?, notes = ?
            WHERE id = ?
        ''', (subject_id, hours_spent, study_date, notes, log_id))
        conn.commit()
        conn.close()

        flash('Study session updated successfully!', 'success')
        return redirect(url_for('student_dashboard'))

    conn.close()
    return render_template('edit_study_log.html', log=log, subjects=subjects)


@app.route('/student/toggle-task/<int:task_id>', methods=['POST'])
@login_required
@student_required
def toggle_task(task_id):
    """Toggle task completion status."""
    conn = get_db_connection()
    task = conn.execute('''
        SELECT is_completed FROM tasks
        WHERE id = ? AND student_id = ?
    ''', (task_id, session['user_id'])).fetchone()

    if not task:
        flash('Task not found or you do not have permission to edit it.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    new_status = 0 if task['is_completed'] else 1
    conn.execute('''
        UPDATE tasks SET is_completed = ?
        WHERE id = ?
    ''', (new_status, task_id))
    conn.commit()
    conn.close()

    status_text = 'completed' if new_status else 'pending'
    flash(f'Task marked as {status_text}!', 'success')
    return redirect(url_for('student_dashboard'))


# ----- Teacher Routes -----

@app.route('/teacher/dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    """Teacher's main dashboard."""
    conn = get_db_connection()
    
    # Get all students
    students = conn.execute('''
        SELECT * FROM users WHERE role = 'student' ORDER BY full_name
    ''').fetchall()
    
    # Get recent activity by student
    recent_logs = conn.execute('''
        SELECT u.id as student_id,
               u.full_name as student_name,
               MAX(sl.created_at) as last_activity,
               COUNT(DISTINCT sl.subject_id) as subjects_covered,
               SUM(sl.hours_spent) as total_hours
        FROM study_logs sl
        JOIN users u ON sl.student_id = u.id
        GROUP BY sl.student_id
        ORDER BY last_activity DESC
        LIMIT 20
    ''').fetchall()
    
    # Get class average trend across exams
    exam_averages = conn.execute('''
        SELECT exam_name,
               ROUND(AVG(marks_obtained / max_marks * 100), 1) as average_percentage,
               COUNT(DISTINCT student_id) as student_count
        FROM marks
        GROUP BY exam_name
        ORDER BY CASE exam_name 
                 WHEN 'Class Test 01' THEN 1 
                 WHEN 'Class Test 02' THEN 2 
                 WHEN 'Internal Examination' THEN 3 
                 WHEN 'End Semester Examination' THEN 4 
                 ELSE 5 
             END
    ''').fetchall()
    
    class_trend = []
    for row in exam_averages:
        class_trend.append({
            'exam_name': row['exam_name'],
            'average': row['average_percentage']
        })
    
    conn.close()
    
    return render_template('teacher_dashboard.html',
                         students=students,
                         recent_logs=recent_logs,
                         class_trend=class_trend)



@app.route('/teacher/edit-mark/<int:mark_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_mark(mark_id):
    conn = get_db_connection()
    mark = conn.execute('''
        SELECT m.*, u.full_name as student_name
        FROM marks m
        JOIN users u ON m.student_id = u.id
        WHERE m.id = ? AND m.entered_by = ?
    ''', (mark_id, session['user_id'])).fetchone()

    if not mark:
        flash('Mark not found or you do not have permission to edit it.', 'error')
        conn.close()
        return redirect(url_for('teacher_dashboard'))

    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()

    if request.method == 'POST':
        subject_id = request.form['subject_id']
        marks_obtained = float(request.form['marks_obtained'])
        max_marks = float(request.form['max_marks'])
        exam_name = request.form['exam_name']

        conn.execute('''
            UPDATE marks
            SET subject_id = ?, marks_obtained = ?, max_marks = ?, exam_name = ?
            WHERE id = ?
        ''', (subject_id, marks_obtained, max_marks, exam_name, mark_id))
        conn.commit()
        conn.close()

        flash('Mark updated successfully!', 'success')
        return redirect(url_for('student_progress', student_id=mark['student_id']))

    conn.close()
    return render_template('edit_mark.html', mark=mark, subjects=subjects)


@app.route('/teacher/edit-task/<int:task_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_task(task_id):
    conn = get_db_connection()
    task = conn.execute('''
        SELECT t.*, u.full_name as student_name
        FROM tasks t
        JOIN users u ON t.student_id = u.id
        WHERE t.id = ? AND t.teacher_id = ?
    ''', (task_id, session['user_id'])).fetchone()

    if not task:
        flash('Task not found or you do not have permission to edit it.', 'error')
        conn.close()
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form.get('description', '')
        due_date = request.form.get('due_date') or None

        conn.execute('''
            UPDATE tasks
            SET title = ?, description = ?, due_date = ?
            WHERE id = ?
        ''', (title, description, due_date, task_id))
        conn.commit()
        conn.close()

        flash('Task updated successfully!', 'success')
        return redirect(url_for('student_progress', student_id=task['student_id']))

    conn.close()
    return render_template('edit_task.html', task=task)


@app.route('/teacher/enter-marks', methods=['GET', 'POST'])
@login_required
@teacher_required
def enter_marks():
    """Enter marks for multiple students."""
    conn = get_db_connection()
    students_rows = conn.execute('''
        SELECT * FROM users WHERE role = 'student' ORDER BY full_name
    ''').fetchall()
    subjects_rows = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    
    # Convert Row objects to dictionaries
    students = [dict(student) for student in students_rows]
    subjects = [dict(subject) for subject in subjects_rows]
    
    if request.method == 'POST':
        subject_id = request.form.get('subject_id')
        exam_name = request.form.get('exam_name')
        
        # Get all student marks data
        student_ids = request.form.getlist('student_id')
        marks_obtained_list = request.form.getlist('marks_obtained[]')
        max_marks_list = request.form.getlist('max_marks[]')
        
        if student_ids and subject_id and exam_name:
            try:
                subject_row = conn.execute('SELECT name FROM subjects WHERE id = ?', (subject_id,)).fetchone()
                subject_name = subject_row['name'] if subject_row else 'a subject'
                for i, student_id in enumerate(student_ids):
                    marks_obtained = marks_obtained_list[i]
                    max_marks = max_marks_list[i] if max_marks_list[i] else '100'
                    
                    # Only insert if marks are provided
                    if marks_obtained and marks_obtained.strip():
                        conn.execute('''
                            INSERT INTO marks (student_id, subject_id, marks_obtained, max_marks, exam_name, entered_by)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (student_id, subject_id, float(marks_obtained), float(max_marks), exam_name, session['user_id']))
                        notify(conn, student_id,
                               f"📊 Marks posted for {subject_name} — {exam_name}",
                               '/student/results')
                
                conn.commit()
                flash('Marks entered successfully for all students!', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Error entering marks: {str(e)}', 'error')
        
        conn.close()
        return redirect(url_for('teacher_dashboard'))
    
    conn.close()
    return render_template('enter_marks.html', students=students, subjects=subjects)

@app.route('/teacher/assign-task', methods=['GET', 'POST'])
@login_required
@teacher_required
def assign_task():
    """Assign a task to a student."""
    conn = get_db_connection()
    students = conn.execute('''
        SELECT * FROM users WHERE role = 'student' ORDER BY full_name
    ''').fetchall()
    
    if request.method == 'POST':
        student_id = request.form['student_id']
        title = request.form['title']
        description = request.form.get('description', '')
        due_date = request.form.get('due_date')
        
        conn.execute('''
            INSERT INTO tasks (student_id, teacher_id, title, description, due_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (student_id, session['user_id'], title, description, due_date or None))
        notify(conn, student_id,
               f"📋 New task from {session['full_name']}: {title}",
               '/student/dashboard')
        conn.commit()
        conn.close()
        
        flash('Task assigned successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))
    
    conn.close()
    return render_template('assign_task.html', students=students)

@app.route('/teacher/student-study/<int:student_id>')
@login_required
@teacher_required
def student_study_activity(student_id):
    """View study sessions only for a specific student."""
    conn = get_db_connection()

    student = conn.execute(
        'SELECT * FROM users WHERE id = ?', (student_id,)
    ).fetchone()

    if not student:
        flash('Student not found.', 'error')
        conn.close()
        return redirect(url_for('teacher_dashboard'))

    study_logs = conn.execute('''
        SELECT sl.*, s.name as subject_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.student_id = ?
        ORDER BY sl.study_date DESC
    ''', (student_id,)).fetchall()

    conn.close()
    return render_template('student_progress.html',
                         student=student,
                         study_logs=study_logs,
                         results=[],
                         tasks=[],
                         show_full_progress=False)


@app.route('/teacher/student-progress/<int:student_id>/exam/<exam_name>')
@login_required
@teacher_required
def student_progress_exam(student_id, exam_name):
    """View subject-level results for a specific exam."""
    conn = get_db_connection()

    student = conn.execute(
        'SELECT * FROM users WHERE id = ?', (student_id,)
    ).fetchone()

    if not student:
        flash('Student not found.', 'error')
        conn.close()
        return redirect(url_for('teacher_dashboard'))

    exam_rows = conn.execute('''
        SELECT m.exam_name,
               COUNT(*) AS subject_count,
               SUM(m.marks_obtained) AS total_obtained,
               SUM(m.max_marks) AS total_max,
               MAX(m.created_at) AS last_entered
        FROM marks m
        WHERE m.student_id = ?
        GROUP BY m.exam_name
        ORDER BY last_entered DESC
    ''', (student_id,)).fetchall()

    exam_list = []
    for exam in exam_rows:
        percentage = (exam['total_obtained'] / exam['total_max']) * 100 if exam['total_max'] else 0
        exam_list.append({
            'exam_name': exam['exam_name'],
            'subject_count': exam['subject_count'],
            'total_obtained': exam['total_obtained'],
            'total_max': exam['total_max'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'last_entered': exam['last_entered']
        })

    exam_results = conn.execute('''
        SELECT m.*, s.name as subject_name, u.full_name as teacher_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        JOIN users u ON m.entered_by = u.id
        WHERE m.student_id = ? AND m.exam_name = ?
        ORDER BY m.created_at DESC
    ''', (student_id, exam_name)).fetchall()

    results = []
    for mark in exam_results:
        percentage = (mark['marks_obtained'] / mark['max_marks']) * 100 if mark['max_marks'] else 0
        results.append({
            'id': mark['id'],
            'subject_name': mark['subject_name'],
            'exam_name': mark['exam_name'],
            'marks_obtained': mark['marks_obtained'],
            'max_marks': mark['max_marks'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'can_edit': mark['entered_by'] == session['user_id']
        })

    tasks = conn.execute('''
        SELECT t.*, u.full_name as student_name
        FROM tasks t
        JOIN users u ON t.student_id = u.id
        WHERE t.student_id = ? AND t.teacher_id = ?
        ORDER BY t.is_completed ASC, t.due_date ASC
    ''', (student_id, session['user_id'])).fetchall()

    conn.close()

    return render_template('student_progress.html',
                         student=student,
                         exam_list=exam_list,
                         exam_results=results,
                         selected_exam=exam_name,
                         tasks=tasks,
                         show_full_progress=True)


@app.route('/teacher/student-progress/<int:student_id>')
@login_required
@teacher_required
def student_progress(student_id):
    """View detailed progress for a specific student."""
    conn = get_db_connection()

    student = conn.execute(
        'SELECT * FROM users WHERE id = ?', (student_id,)
    ).fetchone()

    if not student:
        flash('Student not found.', 'error')
        conn.close()
        return redirect(url_for('teacher_dashboard'))

    # Get study logs
    study_logs = conn.execute('''
        SELECT sl.*, s.name as subject_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.student_id = ?
        ORDER BY sl.study_date DESC
    ''', (student_id,)).fetchall()

    # Get exam summaries
    exam_rows = conn.execute('''
        SELECT m.exam_name,
               COUNT(*) AS subject_count,
               SUM(m.marks_obtained) AS total_obtained,
               SUM(m.max_marks) AS total_max,
               MAX(m.created_at) AS last_entered
        FROM marks m
        WHERE m.student_id = ?
        GROUP BY m.exam_name
        ORDER BY last_entered DESC
    ''', (student_id,)).fetchall()

    exam_list = []
    for exam in exam_rows:
        percentage = (exam['total_obtained'] / exam['total_max']) * 100 if exam['total_max'] else 0
        exam_list.append({
            'exam_name': exam['exam_name'],
            'subject_count': exam['subject_count'],
            'total_obtained': exam['total_obtained'],
            'total_max': exam['total_max'],
            'percentage': round(percentage, 2),
            'grade': calculate_grade(percentage),
            'last_entered': exam['last_entered']
        })

    tasks = conn.execute('''
        SELECT t.*, u.full_name as student_name
        FROM tasks t
        JOIN users u ON t.student_id = u.id
        WHERE t.student_id = ? AND t.teacher_id = ?
        ORDER BY t.is_completed ASC, t.due_date ASC
    ''', (student_id, session['user_id'])).fetchall()

    conn.close()

    return render_template('student_progress.html',
                         student=student,
                         exam_list=exam_list,
                         tasks=tasks,
                         show_full_progress=True)

# ----- Notifications -----

@app.route('/notifications')
@login_required
def notifications():
    """List the user's notifications and mark them as read."""
    conn = get_db_connection()
    notes = conn.execute('''
        SELECT * FROM notifications WHERE user_id = ?
        ORDER BY created_at DESC LIMIT 50
    ''', (session['user_id'],)).fetchall()
    conn.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (session['user_id'],))
    conn.commit()
    conn.close()
    return render_template('notifications.html', notes=notes)


# ----- Calendar -----

@app.route('/student/calendar')
@login_required
@student_required
def student_calendar():
    """Month calendar showing task due dates."""
    import calendar as cal

    today = date.today()
    try:
        year = int(request.args.get('year', today.year))
        month = int(request.args.get('month', today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT t.*, u.full_name AS teacher_name
        FROM tasks t JOIN users u ON t.teacher_id = u.id
        WHERE t.student_id = ? AND t.due_date IS NOT NULL
    ''', (session['user_id'],)).fetchall()
    conn.close()

    # Group tasks by due date string YYYY-MM-DD
    tasks_by_day = {}
    for t in tasks:
        tasks_by_day.setdefault(t['due_date'], []).append(t)

    month_grid = cal.Calendar(firstweekday=0).monthdayscalendar(year, month)  # weeks of day numbers, 0 = padding
    weeks = []
    for week in month_grid:
        row = []
        for day in week:
            if day == 0:
                row.append(None)
            else:
                key = f"{year:04d}-{month:02d}-{day:02d}"
                row.append({
                    'day': day,
                    'is_today': (year == today.year and month == today.month and day == today.day),
                    'tasks': tasks_by_day.get(key, [])
                })
        weeks.append(row)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return render_template('calendar.html',
                           weeks=weeks,
                           month_name=cal.month_name[month],
                           year=year,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)


# ----- Leaderboard -----

@app.route('/student/leaderboard')
@login_required
@student_required
def leaderboard():
    """Study streak and hours leaderboard for all active students."""
    conn = get_db_connection()
    students = conn.execute('''
        SELECT id, full_name FROM users
        WHERE role = 'student' AND status = 'active'
    ''').fetchall()

    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    board = []
    for s in students:
        streak = compute_streak(conn, s['id'])
        hours_row = conn.execute('''
            SELECT COALESCE(SUM(hours_spent), 0) AS h FROM study_logs
            WHERE student_id = ? AND study_date >= ?
        ''', (s['id'], thirty_days_ago)).fetchone()
        icon, label = streak_badge(streak)
        board.append({
            'id': s['id'],
            'name': s['full_name'],
            'streak': streak,
            'hours': round(hours_row['h'], 1),
            'badge_icon': icon,
            'badge_label': label,
            'is_me': s['id'] == session['user_id']
        })
    conn.close()

    board.sort(key=lambda x: (-x['streak'], -x['hours']))
    my_entry = next((b for b in board if b['is_me']), None)
    my_rank = board.index(my_entry) + 1 if my_entry else None

    return render_template('leaderboard.html', board=board, my_rank=my_rank, my_entry=my_entry)


# ----- PDF Report Cards -----

def build_report_card_pdf(conn, student):
    """Generate a PDF report card for a student. Returns the PDF as bytes."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    marks = conn.execute('''
        SELECT m.*, s.name AS subject_name
        FROM marks m JOIN subjects s ON m.subject_id = s.id
        WHERE m.student_id = ?
        ORDER BY m.exam_name, s.name
    ''', (student['id'],)).fetchall()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            leftMargin=1.8 * cm, rightMargin=1.8 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Title'], textColor=colors.HexColor('#4f46e5'))
    elements = []

    elements.append(Paragraph('Student Academic Management System', title_style))
    elements.append(Paragraph('Official Report Card', styles['Heading2']))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"<b>Student:</b> {student['full_name']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Username:</b> {student['username']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Generated:</b> {date.today().strftime('%d %B %Y')}", styles['Normal']))
    elements.append(Spacer(1, 14))

    if not marks:
        elements.append(Paragraph('No marks have been entered yet.', styles['Normal']))
    else:
        # Group marks by exam
        exams = {}
        for m in marks:
            exams.setdefault(m['exam_name'], []).append(m)

        for exam_name, exam_marks in exams.items():
            elements.append(Paragraph(exam_name, styles['Heading3']))
            data = [['Subject', 'Marks', 'Out of', 'Percentage', 'Grade']]
            total_o, total_m = 0, 0
            for m in exam_marks:
                pct = (m['marks_obtained'] / m['max_marks'] * 100) if m['max_marks'] else 0
                total_o += m['marks_obtained']
                total_m += m['max_marks']
                data.append([m['subject_name'],
                             f"{m['marks_obtained']:g}",
                             f"{m['max_marks']:g}",
                             f"{pct:.1f}%",
                             calculate_grade(pct)])
            overall_pct = (total_o / total_m * 100) if total_m else 0
            data.append(['TOTAL', f"{total_o:g}", f"{total_m:g}",
                         f"{overall_pct:.1f}%", calculate_grade(overall_pct)])

            table = Table(data, colWidths=[6.5 * cm, 2.5 * cm, 2.5 * cm, 3 * cm, 2 * cm])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#eef2ff')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c7c9d9')),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 14))

    elements.append(Spacer(1, 20))
    footer_style = ParagraphStyle('F', parent=styles['Normal'], textColor=colors.grey, fontSize=8)
    elements.append(Paragraph('Generated by SAMS - Student Academic Management System', footer_style))

    doc.build(elements)
    return buf.getvalue()


@app.route('/student/report-card')
@login_required
@student_required
def student_report_card():
    """Student downloads their own report card as PDF."""
    from flask import Response
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    pdf = build_report_card_pdf(conn, student)
    conn.close()
    filename = f"report_card_{student['username']}.pdf"
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@app.route('/teacher/report-card/<int:student_id>')
@login_required
@teacher_required
def teacher_report_card(student_id):
    """Teacher downloads a student's report card as PDF."""
    from flask import Response
    conn = get_db_connection()
    student = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'student'", (student_id,)
    ).fetchone()
    if not student:
        conn.close()
        flash('Student not found.', 'error')
        return redirect(url_for('teacher_dashboard'))
    pdf = build_report_card_pdf(conn, student)
    conn.close()
    filename = f"report_card_{student['username']}.pdf"
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


# Run the app
if __name__ == '__main__':
    with get_db_connection() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN theme VARCHAR(10) DEFAULT 'light'")
            conn.commit()
        except Exception:
            pass
    # Debug mode is OFF unless you explicitly set FLASK_DEBUG=1 on your own laptop.
    # Never enable debug on a real server - it exposes your code to attackers.
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
