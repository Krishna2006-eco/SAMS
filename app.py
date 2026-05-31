from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date, timedelta
from database import get_db_connection, init_db
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

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

        conn = get_db_connection()
        
        # Check if username already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ?', (username,)
        ).fetchone()
        
        if existing_user:
            flash('Username already exists. Please choose another.', 'error')
            conn.close()
            return redirect(url_for('register'))
        
        # Insert new user with pending approval
        conn.execute(
            'INSERT INTO users (username, password, role, full_name, status) VALUES (?, ?, ?, ?, ?)',
            (username, password, role, full_name, 'pending')
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
            'SELECT * FROM users WHERE username = ? AND password = ?',
            (username, password)
        ).fetchone()
        conn.close()
        
        if user:
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

@app.route('/logout')
def logout():
    """Log out the user."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# ----- Student Routes -----

@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    """Student's main dashboard."""
    conn = get_db_connection()
    
    # Get recent study logs
    study_logs = conn.execute('''
        SELECT sl.*, s.name as subject_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.student_id = ?
        ORDER BY sl.study_date DESC
        LIMIT 10
    ''', (session['user_id'],)).fetchall()
    
    # Get total hours studied per subject
    study_summary = conn.execute('''
        SELECT s.name as subject_name, SUM(sl.hours_spent) as total_hours
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.student_id = ?
        GROUP BY s.id
        ORDER BY total_hours DESC
    ''', (session['user_id'],)).fetchall()
    
    # Get assigned tasks
    tasks = conn.execute('''
        SELECT t.*, u.full_name as teacher_name
        FROM tasks t
        JOIN users u ON t.teacher_id = u.id
        WHERE t.student_id = ?
        ORDER BY t.is_completed ASC, t.due_date ASC
    ''', (session['user_id'],)).fetchall()
    
    # Calculate study streak (consecutive days ending today)
    streak_rows = conn.execute('''
        SELECT DISTINCT study_date
        FROM study_logs
        WHERE student_id = ?
        ORDER BY study_date DESC
    ''', (session['user_id'],)).fetchall()

    streak = 0
    if streak_rows:
        study_dates = [datetime.fromisoformat(row['study_date']).date() for row in streak_rows]
        today = date.today()

        if study_dates[0] == today:
            streak = 1
            for next_date in study_dates[1:]:
                expected_date = today - timedelta(days=streak)
                if next_date == expected_date:
                    streak += 1
                else:
                    break

    conn.close()

    return render_template('student_dashboard.html',
                         study_logs=study_logs,
                         study_summary=study_summary,
                         tasks=tasks,
                         streak=streak)

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

    return render_template('view_results.html',
                         exam_list=exam_list,
                         selected_exam=None,
                         exam_results=[],
                         total_obtained=total_obtained,
                         total_max=total_max,
                         overall_percentage=round(overall_percentage, 2),
                         overall_grade=overall_grade,
                         rank_info=rank_info)


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

    return render_template('view_results.html',
                         exam_list=exam_list,
                         selected_exam=exam_name,
                         exam_results=exam_results,
                         total_obtained=total_obtained,
                         total_max=total_max,
                         overall_percentage=round(overall_percentage, 2),
                         overall_grade=overall_grade,
                         rank_info=rank_info)


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
    
    conn.close()
    
    return render_template('teacher_dashboard.html',
                         students=students,
                         recent_logs=recent_logs)



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
                for i, student_id in enumerate(student_ids):
                    marks_obtained = marks_obtained_list[i]
                    max_marks = max_marks_list[i] if max_marks_list[i] else '100'
                    
                    # Only insert if marks are provided
                    if marks_obtained and marks_obtained.strip():
                        conn.execute('''
                            INSERT INTO marks (student_id, subject_id, marks_obtained, max_marks, exam_name, entered_by)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (student_id, subject_id, float(marks_obtained), float(max_marks), exam_name, session['user_id']))
                
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

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
