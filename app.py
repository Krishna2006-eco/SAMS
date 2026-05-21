from flask import Flask, render_template, request, redirect, url_for, session, flash
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
        
        conn = get_db_connection()
        
        # Check if username already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ?', (username,)
        ).fetchone()
        
        if existing_user:
            flash('Username already exists. Please choose another.', 'error')
            conn.close()
            return redirect(url_for('register'))
        
        # Insert new user
        conn.execute(
            'INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)',
            (username, password, role, full_name)
        )
        conn.commit()
        conn.close()
        
        flash('Registration successful! Please log in.', 'success')
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
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            
            flash(f'Welcome back, {user["full_name"]}!', 'success')
            
            if user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

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
    
    # Calculate study streak (consecutive days)
    streak = conn.execute('''
        SELECT COUNT (DISTINCT study_date) as days
        FROM study_logs
        WHERE student_id = ?
        ORDER BY study_date > DATE('now') DESC
    ''', (session['user_id'],)).fetchone()
    
    conn.close()
    
    return render_template('student_dashboard.html',
                         study_logs=study_logs,
                         study_summary=study_summary,
                         tasks=tasks,
                         streak=streak['days'] if streak else 0)

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
    """View marks and grades."""
    conn = get_db_connection()
    
    # Get all marks for this student
    marks = conn.execute('''
        SELECT m.*, s.name as subject_name, u.full_name as teacher_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        JOIN users u ON m.entered_by = u.id
        WHERE m.student_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Calculate totals and grade for each exam
    results = []
    for mark in marks:
        percentage = (mark['marks_obtained'] / mark['max_marks']) * 100
        grade = calculate_grade(percentage)
        results.append({
            'subject_name': mark['subject_name'],
            'exam_name': mark['exam_name'],
            'marks_obtained': mark['marks_obtained'],
            'max_marks': mark['max_marks'],
            'percentage': round(percentage, 2),
            'grade': grade,
            'teacher_name': mark['teacher_name']
        })
    
    # Calculate overall statistics
    if results:
        total_obtained = sum(r['marks_obtained'] for r in results)
        total_max = sum(r['max_marks'] for r in results)
        overall_percentage = (total_obtained / total_max) * 100 if total_max > 0 else 0
        overall_grade = calculate_grade(overall_percentage)
    else:
        total_obtained = 0
        total_max = 0
        overall_percentage = 0
        overall_grade = 'N/A'
    
    # Get rank among all students (for the most recent exam)
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
                         results=results,
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
    
    # Get recent study logs from all students
    recent_logs = conn.execute('''
        SELECT sl.*, s.name as subject_name, u.full_name as student_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        JOIN users u ON sl.student_id = u.id
        ORDER BY sl.created_at DESC
        LIMIT 20
    ''').fetchall()
    
    conn.close()
    
    return render_template('teacher_dashboard.html',
                         students=students,
                         recent_logs=recent_logs)

@app.route('/teacher/enter-marks', methods=['GET', 'POST'])
@login_required
@teacher_required
def enter_marks():
    """Enter marks for a student."""
    conn = get_db_connection()
    students = conn.execute('''
        SELECT * FROM users WHERE role = 'student' ORDER BY full_name
    ''').fetchall()
    subjects = conn.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    
    if request.method == 'POST':
        student_id = request.form['student_id']
        subject_id = request.form['subject_id']
        marks_obtained = float(request.form['marks_obtained'])
        max_marks = float(request.form['max_marks'])
        exam_name = request.form['exam_name']
        
        conn.execute('''
            INSERT INTO marks (student_id, subject_id, marks_obtained, max_marks, exam_name, entered_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (student_id, subject_id, marks_obtained, max_marks, exam_name, session['user_id']))
        conn.commit()
        conn.close()
        
        flash('Marks entered successfully!', 'success')
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
        return redirect(url_for('teacher_dashboard'))
    
    # Get study logs
    study_logs = conn.execute('''
        SELECT sl.*, s.name as subject_name
        FROM study_logs sl
        JOIN subjects s ON sl.subject_id = s.id
        WHERE sl.student_id = ?
        ORDER BY sl.study_date DESC
    ''', (student_id,)).fetchall()
    
    # Get marks
    marks = conn.execute('''
        SELECT m.*, s.name as subject_name
        FROM marks m
        JOIN subjects s ON m.subject_id = s.id
        WHERE m.student_id = ?
        ORDER BY m.created_at DESC
    ''', (student_id,)).fetchall()
    
    # Calculate results with grades
    results = []
    for mark in marks:
        percentage = (mark['marks_obtained'] / mark['max_marks']) * 100
        grade = calculate_grade(percentage)
        results.append({
            'subject_name': mark['subject_name'],
            'exam_name': mark['exam_name'],
            'marks_obtained': mark['marks_obtained'],
            'max_marks': mark['max_marks'],
            'percentage': round(percentage, 2),
            'grade': grade
        })
    
    conn.close()
    
    return render_template('student_progress.html',
                         student=student,
                         study_logs=study_logs,
                         results=results)

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
