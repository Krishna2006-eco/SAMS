import sqlite3

DATABASE = 'study_tracker.db'

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
                department TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            INSERT INTO users_new (id, username, password, role, full_name, status, department, created_at)
            SELECT id, username, password, role, full_name,
                   COALESCE(status, 'pending'), department, created_at
            FROM users
        ''')
        cursor.execute('DROP TABLE users')
        cursor.execute('ALTER TABLE users_new RENAME TO users')
        cursor.execute('COMMIT')
        cursor.execute('PRAGMA foreign_keys = ON')

    # Ensure existing users are not locked out after migration.
    cursor.execute("UPDATE users SET status = 'active' WHERE status IS NULL AND role IN ('teacher', 'student', 'admin')")
    
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
