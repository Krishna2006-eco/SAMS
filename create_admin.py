import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from database import get_db_connection, init_db
from werkzeug.security import generate_password_hash


def main():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    existing_admin = cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if existing_admin:
        print('An admin account already exists. No new admin was created.')
        conn.close()
        return

    username = input('Enter admin username: ').strip()
    password = input('Enter admin password: ').strip()

    if not username or not password:
        print('Username and password are required.')
        conn.close()
        return

    existing_user = cursor.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if existing_user:
        print('A user with that username already exists. Choose a different username.')
        conn.close()
        return

    cursor.execute(
        'INSERT INTO users (username, password, role, full_name, status) VALUES (?, ?, ?, ?, ?)',
        (username, generate_password_hash(password), 'admin', username, 'active')
    )
    conn.commit()
    conn.close()

    print(f'Admin account "{username}" created successfully and is active.')


if __name__ == '__main__':
    main()
