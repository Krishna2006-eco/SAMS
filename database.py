import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = str(BASE_DIR / 'study_tracker.db')

def get_db_connection():
    """Create a connection to the database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # This lets us access columns by name
    return conn

def init_db():
    """Create all the tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table - stores both teachers and students
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher', 'student', 'admin')),
            full_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'active', 'blocked')) DEFAULT 'pending',
            theme TEXT NOT NULL DEFAULT 'light',
            department TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Ensure the department and status columns exist for older databases.
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()]
    if 'department' not in existing_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN department TEXT')
    if 'status' not in existing_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN status VARCHAR(20) DEFAULT 'pending'")
        except sqlite3.OperationalError:
            pass
    if 'theme' not in existing_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN theme VARCHAR(10) DEFAULT 'light'")
        except sqlite3.OperationalError:
            pass

    # If the old users table still has the old role constraint, rebuild it with admin support.
    current_sql_row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if current_sql_row and "CHECK(role IN ('teacher', 'student'))" in current_sql_row[0]:
        cursor.execute('PRAGMA foreign_keys = OFF')
        cursor.execute('BEGIN TRANSACTION')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('teacher', 'student', 'admin')),
                full_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'active', 'blocked')) DEFAULT 'pending',
                theme TEXT NOT NULL DEFAULT 'light',
                department TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            INSERT INTO users_new (id, username, password, role, full_name, status, theme, department, created_at)
            SELECT id, username, password, role, full_name,
                   COALESCE(status, 'pending'), COALESCE(theme, 'light'), department, created_at
            FROM users
        ''')
        cursor.execute('DROP TABLE users')
        cursor.execute('ALTER TABLE users_new RENAME TO users')
        cursor.execute('COMMIT')
        cursor.execute('PRAGMA foreign_keys = ON')

    # Ensure existing users are not locked out after migration.
    cursor.execute("UPDATE users SET status = 'active' WHERE status IS NULL AND role IN ('teacher', 'student', 'admin')")
    cursor.execute("UPDATE users SET theme = 'light' WHERE theme IS NULL")
    
    # Subjects table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Study logs - students record their study sessions here
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS study_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            hours_spent REAL NOT NULL,
            study_date DATE NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id)
        )
    ''')
    
    # Marks - teachers enter marks here
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            marks_obtained REAL NOT NULL,
            max_marks REAL NOT NULL DEFAULT 100,
            exam_name TEXT NOT NULL,
            entered_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (entered_by) REFERENCES users(id)
        )
    ''')
    
    # Tasks - teachers assign tasks to students
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date DATE,
            is_completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')
    
    # Notifications - in-app alerts for users (new marks, new tasks, etc.)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Classrooms - a teacher-owned group that students join with a code
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher_id INTEGER NOT NULL,
            join_code TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # Classroom membership - which students belong to which classroom
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classroom_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
            FOREIGN KEY (student_id) REFERENCES users(id),
            UNIQUE(classroom_id, student_id)
        )
    ''')

    # Classroom posts - announcements/material posted by the teacher, optionally with a file
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classroom_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classroom_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            file_name TEXT,
            file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
            FOREIGN KEY (author_id) REFERENCES users(id)
        )
    ''')

    # Comments on a classroom post - students (and the teacher) can reply, optionally with a file
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classroom_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            file_name TEXT,
            file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES classroom_posts(id),
            FOREIGN KEY (author_id) REFERENCES users(id)
        )
    ''')

    # Conversations - one row per unique pair of users having a 1-on-1 chat
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_a) REFERENCES users(id),
            FOREIGN KEY (user_b) REFERENCES users(id),
            UNIQUE(user_a, user_b)
        )
    ''')

    # Direct messages - texts (and optional file attachments) within a conversation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT,
            file_name TEXT,
            file_path TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    ''')

    # Insert default subjects if they don't exist
    default_subjects = ['Mathematics', 'Science', 'English', 'History', 'Geography']
    for subject in default_subjects:
        cursor.execute('INSERT OR IGNORE INTO subjects (name) VALUES (?)', (subject,))
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

# Run this when the file is executed directly
if __name__ == '__main__':
    init_db()
