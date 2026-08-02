import secrets
import string
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, send_from_directory, abort
)
from werkzeug.utils import secure_filename

from database import get_db_connection

chat = Blueprint('chat', __name__, url_prefix='/chat')

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = BASE_DIR / 'chat_uploads'

# Keep this deliberately conservative - no executables or scripts.
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'csv',
    'png', 'jpg', 'jpeg', 'gif', 'zip', 'mp3', 'mp4', 'odt', 'rtf'
}
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


# ----- Local auth decorators (mirrors app.py; kept local to avoid a circular import) -----

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'teacher':
            flash('This page is for teachers only.', 'error')
            return redirect(url_for('chat.inbox'))
        return f(*args, **kwargs)
    return decorated


def student_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'student':
            flash('This page is for students only.', 'error')
            return redirect(url_for('chat.inbox'))
        return f(*args, **kwargs)
    return decorated


# ----- Helpers -----

def notify(conn, user_id, message, link=None):
    conn.execute(
        'INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)',
        (user_id, message, link)
    )


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    """Save an uploaded file to disk with a random name. Returns (display_name, stored_name, error)."""
    if not file_storage or file_storage.filename == '':
        return None, None, None

    display_name = secure_filename(file_storage.filename)
    if not display_name or not allowed_file(display_name):
        return None, None, 'That file type is not allowed.'

    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_FILE_BYTES:
        return None, None, 'That file is too large (20 MB max).'

    ext = display_name.rsplit('.', 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    file_storage.save(str(UPLOAD_ROOT / stored_name))
    return display_name, stored_name, None


def generate_join_code(conn):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        exists = conn.execute('SELECT 1 FROM classrooms WHERE join_code = ?', (code,)).fetchone()
        if not exists:
            return code


def get_classroom_or_404(conn, classroom_id):
    classroom = conn.execute('SELECT * FROM classrooms WHERE id = ?', (classroom_id,)).fetchone()
    if not classroom:
        abort(404)
    return classroom


def is_classroom_member(conn, classroom, user_id, role):
    if role == 'teacher':
        return classroom['teacher_id'] == user_id
    if role == 'admin':
        return True
    return conn.execute(
        'SELECT 1 FROM classroom_members WHERE classroom_id = ? AND student_id = ?',
        (classroom['id'], user_id)
    ).fetchone() is not None


def get_or_create_conversation(conn, user_a, user_b):
    lo, hi = sorted((user_a, user_b))
    convo = conn.execute(
        'SELECT * FROM conversations WHERE user_a = ? AND user_b = ?', (lo, hi)
    ).fetchone()
    if convo:
        return convo['id']
    cur = conn.execute('INSERT INTO conversations (user_a, user_b) VALUES (?, ?)', (lo, hi))
    return cur.lastrowid


# ----- Inbox -----

@chat.route('/')
@login_required
def inbox():
    conn = get_db_connection()
    user_id = session['user_id']
    role = session.get('role')

    if role == 'teacher':
        classrooms = conn.execute(
            'SELECT *, (SELECT COUNT(*) FROM classroom_members WHERE classroom_id = classrooms.id) AS member_count '
            'FROM classrooms WHERE teacher_id = ? ORDER BY created_at DESC', (user_id,)
        ).fetchall()
    else:
        classrooms = conn.execute('''
            SELECT c.*, (SELECT COUNT(*) FROM classroom_members WHERE classroom_id = c.id) AS member_count
            FROM classrooms c
            JOIN classroom_members m ON m.classroom_id = c.id
            WHERE m.student_id = ?
            ORDER BY c.created_at DESC
        ''', (user_id,)).fetchall()

    conversations = conn.execute('''
        SELECT conv.id AS conversation_id,
               u.id AS other_id, u.full_name AS other_name, u.role AS other_role,
               (SELECT content FROM direct_messages WHERE conversation_id = conv.id ORDER BY created_at DESC LIMIT 1) AS last_message,
               (SELECT file_name FROM direct_messages WHERE conversation_id = conv.id ORDER BY created_at DESC LIMIT 1) AS last_file,
               (SELECT created_at FROM direct_messages WHERE conversation_id = conv.id ORDER BY created_at DESC LIMIT 1) AS last_time,
               (SELECT COUNT(*) FROM direct_messages WHERE conversation_id = conv.id AND is_read = 0 AND sender_id != ?) AS unread
        FROM conversations conv
        JOIN users u ON u.id = (CASE WHEN conv.user_a = ? THEN conv.user_b ELSE conv.user_a END)
        WHERE conv.user_a = ? OR conv.user_b = ?
        ORDER BY last_time DESC
    ''', (user_id, user_id, user_id, user_id)).fetchall()

    conn.close()
    return render_template('chat/inbox.html', classrooms=classrooms, conversations=conversations)


# ----- Classrooms -----

@chat.route('/classrooms/new', methods=['GET', 'POST'])
@login_required
@teacher_required
def classroom_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Please give the classroom a name.', 'error')
            return redirect(url_for('chat.classroom_new'))

        conn = get_db_connection()
        code = generate_join_code(conn)
        conn.execute(
            'INSERT INTO classrooms (name, teacher_id, join_code) VALUES (?, ?, ?)',
            (name, session['user_id'], code)
        )
        conn.commit()
        conn.close()
        flash(f'Classroom created! Share join code {code} with your students.', 'success')
        return redirect(url_for('chat.inbox'))

    return render_template('chat/classroom_new.html')


@chat.route('/classrooms/join', methods=['GET', 'POST'])
@login_required
@student_required
def classroom_join():
    if request.method == 'POST':
        code = request.form.get('join_code', '').strip().upper()
        conn = get_db_connection()
        classroom = conn.execute('SELECT * FROM classrooms WHERE join_code = ?', (code,)).fetchone()
        if not classroom:
            flash('No classroom found with that code.', 'error')
            conn.close()
            return redirect(url_for('chat.classroom_join'))

        already = conn.execute(
            'SELECT 1 FROM classroom_members WHERE classroom_id = ? AND student_id = ?',
            (classroom['id'], session['user_id'])
        ).fetchone()
        if already:
            flash("You're already in that classroom.", 'info')
        else:
            conn.execute(
                'INSERT INTO classroom_members (classroom_id, student_id) VALUES (?, ?)',
                (classroom['id'], session['user_id'])
            )
            notify(conn, classroom['teacher_id'],
                   f"🎓 {session['full_name']} joined {classroom['name']}",
                   url_for('chat.classroom_view', classroom_id=classroom['id']))
            conn.commit()
            flash(f"Joined {classroom['name']}!", 'success')
        conn.close()
        return redirect(url_for('chat.classroom_view', classroom_id=classroom['id']))

    return render_template('chat/classroom_join.html')


@chat.route('/classrooms/<int:classroom_id>', methods=['GET'])
@login_required
def classroom_view(classroom_id):
    conn = get_db_connection()
    classroom = get_classroom_or_404(conn, classroom_id)
    role = session.get('role')
    user_id = session['user_id']

    if not is_classroom_member(conn, classroom, user_id, role):
        conn.close()
        flash("You don't have access to that classroom.", 'error')
        return redirect(url_for('chat.inbox'))

    posts = conn.execute('''
        SELECT p.*, u.full_name AS author_name
        FROM classroom_posts p JOIN users u ON u.id = p.author_id
        WHERE p.classroom_id = ? ORDER BY p.created_at DESC
    ''', (classroom_id,)).fetchall()

    comments_by_post = {}
    for post in posts:
        rows = conn.execute('''
            SELECT c.*, u.full_name AS author_name
            FROM classroom_comments c JOIN users u ON u.id = c.author_id
            WHERE c.post_id = ? ORDER BY c.created_at ASC
        ''', (post['id'],)).fetchall()
        comments_by_post[post['id']] = rows

    members = conn.execute('''
        SELECT u.id, u.full_name, u.username
        FROM classroom_members m JOIN users u ON u.id = m.student_id
        WHERE m.classroom_id = ? ORDER BY u.full_name
    ''', (classroom_id,)).fetchall()

    is_teacher = role == 'teacher' and classroom['teacher_id'] == user_id
    conn.close()
    return render_template(
        'chat/classroom_view.html', classroom=classroom, posts=posts,
        comments_by_post=comments_by_post, members=members, is_teacher=is_teacher
    )


@chat.route('/classrooms/<int:classroom_id>/post', methods=['POST'])
@login_required
@teacher_required
def classroom_post(classroom_id):
    conn = get_db_connection()
    classroom = get_classroom_or_404(conn, classroom_id)
    if classroom['teacher_id'] != session['user_id']:
        conn.close()
        flash("You don't own that classroom.", 'error')
        return redirect(url_for('chat.inbox'))

    content = request.form.get('content', '').strip()
    file_storage = request.files.get('attachment')
    display_name, stored_name, error = save_upload(file_storage)
    if error:
        conn.close()
        flash(error, 'error')
        return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))

    if not content and not display_name:
        conn.close()
        flash('Write something or attach a file.', 'error')
        return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))

    conn.execute(
        'INSERT INTO classroom_posts (classroom_id, author_id, content, file_name, file_path) VALUES (?, ?, ?, ?, ?)',
        (classroom_id, session['user_id'], content, display_name, stored_name)
    )

    members = conn.execute(
        'SELECT student_id FROM classroom_members WHERE classroom_id = ?', (classroom_id,)
    ).fetchall()
    for m in members:
        notify(conn, m['student_id'],
               f"📣 New post in {classroom['name']}",
               url_for('chat.classroom_view', classroom_id=classroom_id))

    conn.commit()
    conn.close()
    flash('Posted!', 'success')
    return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))


@chat.route('/classrooms/<int:classroom_id>/posts/<int:post_id>/comment', methods=['POST'])
@login_required
def classroom_comment(classroom_id, post_id):
    conn = get_db_connection()
    classroom = get_classroom_or_404(conn, classroom_id)
    role = session.get('role')
    user_id = session['user_id']

    if not is_classroom_member(conn, classroom, user_id, role):
        conn.close()
        flash("You don't have access to that classroom.", 'error')
        return redirect(url_for('chat.inbox'))

    post = conn.execute(
        'SELECT * FROM classroom_posts WHERE id = ? AND classroom_id = ?', (post_id, classroom_id)
    ).fetchone()
    if not post:
        conn.close()
        abort(404)

    content = request.form.get('content', '').strip()
    file_storage = request.files.get('attachment')
    display_name, stored_name, error = save_upload(file_storage)
    if error:
        conn.close()
        flash(error, 'error')
        return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))

    if not content and not display_name:
        conn.close()
        flash('Write something or attach a file.', 'error')
        return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))

    conn.execute(
        'INSERT INTO classroom_comments (post_id, author_id, content, file_name, file_path) VALUES (?, ?, ?, ?, ?)',
        (post_id, user_id, content, display_name, stored_name)
    )

    notify_targets = {post['author_id'], classroom['teacher_id']}
    notify_targets.discard(user_id)
    for target in notify_targets:
        notify(conn, target,
               f"💬 {session['full_name']} commented in {classroom['name']}",
               url_for('chat.classroom_view', classroom_id=classroom_id))

    conn.commit()
    conn.close()
    return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))


@chat.route('/classrooms/<int:classroom_id>/remove/<int:student_id>', methods=['POST'])
@login_required
@teacher_required
def classroom_remove_member(classroom_id, student_id):
    conn = get_db_connection()
    classroom = get_classroom_or_404(conn, classroom_id)
    if classroom['teacher_id'] != session['user_id']:
        conn.close()
        flash("You don't own that classroom.", 'error')
        return redirect(url_for('chat.inbox'))

    conn.execute(
        'DELETE FROM classroom_members WHERE classroom_id = ? AND student_id = ?',
        (classroom_id, student_id)
    )
    conn.commit()
    conn.close()
    flash('Student removed from classroom.', 'success')
    return redirect(url_for('chat.classroom_view', classroom_id=classroom_id))


# ----- Direct messages -----

@chat.route('/dm/new')
@login_required
def dm_new():
    conn = get_db_connection()
    contacts = conn.execute(
        'SELECT id, full_name, username, role FROM users WHERE id != ? AND status = ? ORDER BY role, full_name',
        (session['user_id'], 'active')
    ).fetchall()
    conn.close()
    return render_template('chat/dm_new.html', contacts=contacts)


@chat.route('/dm/<int:other_id>', methods=['GET', 'POST'])
@login_required
def dm_thread(other_id):
    if other_id == session['user_id']:
        flash("You can't message yourself.", 'error')
        return redirect(url_for('chat.dm_new'))

    conn = get_db_connection()
    other = conn.execute('SELECT * FROM users WHERE id = ?', (other_id,)).fetchone()
    if not other:
        conn.close()
        abort(404)

    conversation_id = get_or_create_conversation(conn, session['user_id'], other_id)

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        file_storage = request.files.get('attachment')
        display_name, stored_name, error = save_upload(file_storage)
        if error:
            flash(error, 'error')
        elif not content and not display_name:
            flash('Write a message or attach a file.', 'error')
        else:
            conn.execute(
                'INSERT INTO direct_messages (conversation_id, sender_id, content, file_name, file_path) '
                'VALUES (?, ?, ?, ?, ?)',
                (conversation_id, session['user_id'], content, display_name, stored_name)
            )
            notify(conn, other_id,
                   f"✉️ New message from {session['full_name']}",
                   url_for('chat.dm_thread', other_id=session['user_id']))
            conn.commit()
        conn.close()
        return redirect(url_for('chat.dm_thread', other_id=other_id))

    conn.execute(
        'UPDATE direct_messages SET is_read = 1 WHERE conversation_id = ? AND sender_id != ?',
        (conversation_id, session['user_id'])
    )
    conn.commit()

    messages = conn.execute(
        'SELECT * FROM direct_messages WHERE conversation_id = ? ORDER BY created_at ASC',
        (conversation_id,)
    ).fetchall()
    conn.close()
    return render_template('chat/dm_thread.html', other=other, messages=messages)


# ----- File downloads (permission-checked) -----

@chat.route('/download/post/<int:post_id>')
@login_required
def download_post_file(post_id):
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM classroom_posts WHERE id = ?', (post_id,)).fetchone()
    if not post or not post['file_path']:
        conn.close()
        abort(404)
    classroom = get_classroom_or_404(conn, post['classroom_id'])
    if not is_classroom_member(conn, classroom, session['user_id'], session.get('role')):
        conn.close()
        abort(403)
    conn.close()
    return send_from_directory(str(UPLOAD_ROOT), post['file_path'], as_attachment=True, download_name=post['file_name'])


@chat.route('/download/comment/<int:comment_id>')
@login_required
def download_comment_file(comment_id):
    conn = get_db_connection()
    comment = conn.execute('SELECT * FROM classroom_comments WHERE id = ?', (comment_id,)).fetchone()
    if not comment or not comment['file_path']:
        conn.close()
        abort(404)
    post = conn.execute('SELECT * FROM classroom_posts WHERE id = ?', (comment['post_id'],)).fetchone()
    classroom = get_classroom_or_404(conn, post['classroom_id'])
    if not is_classroom_member(conn, classroom, session['user_id'], session.get('role')):
        conn.close()
        abort(403)
    conn.close()
    return send_from_directory(str(UPLOAD_ROOT), comment['file_path'], as_attachment=True, download_name=comment['file_name'])


@chat.route('/download/dm/<int:message_id>')
@login_required
def download_dm_file(message_id):
    conn = get_db_connection()
    message = conn.execute('SELECT * FROM direct_messages WHERE id = ?', (message_id,)).fetchone()
    if not message or not message['file_path']:
        conn.close()
        abort(404)
    convo = conn.execute('SELECT * FROM conversations WHERE id = ?', (message['conversation_id'],)).fetchone()
    user_id = session['user_id']
    if session.get('role') != 'admin' and user_id not in (convo['user_a'], convo['user_b']):
        conn.close()
        abort(403)
    conn.close()
    return send_from_directory(str(UPLOAD_ROOT), message['file_path'], as_attachment=True, download_name=message['file_name'])
