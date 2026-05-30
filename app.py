"""
AttendanceApp Backend API
Run: python app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, hashlib, os, base64, datetime, socket

app = Flask(__name__)
CORS(app)  # Allow requests from the frontend

DB_FILE      = 'attendance.db'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row   # Return rows as dicts
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Staff table
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT NOT NULL,
        email     TEXT UNIQUE NOT NULL,
        password  TEXT NOT NULL,
        role      TEXT DEFAULT 'staff',
        created   TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    # Attendance table
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id      INTEGER NOT NULL,
        date          TEXT NOT NULL,
        clock_in      TEXT,
        clock_out     TEXT,
        clock_in_lat  REAL,
        clock_in_lng  REAL,
        clock_out_lat REAL,
        clock_out_lng REAL,
        photo         TEXT,
        status        TEXT DEFAULT 'present',
        FOREIGN KEY (staff_id) REFERENCES staff(id)
    )''')

    # Live locations table
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id   INTEGER NOT NULL,
        latitude   REAL,
        longitude  REAL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (staff_id) REFERENCES staff(id)
    )''')

    # Insert demo staff accounts
    demo_staff = [
        ('Rahul Kumar',  'staff@test.com',  hash_password('1234'),      'staff'),
        ('Priya Sharma', 'priya@test.com',  hash_password('1234'),      'staff'),
        ('Admin User',   'admin@test.com',  hash_password('admin123'),  'admin'),
    ]
    for name, email, pwd, role in demo_staff:
        try:
            c.execute('INSERT INTO staff (name, email, password, role) VALUES (?,?,?,?)',
                      (name, email, pwd, role))
        except sqlite3.IntegrityError:
            pass  # Already exists

    conn.commit()
    conn.close()
    print("✅ Database ready")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data  = request.json
    email = data.get('email', '').strip()
    pwd   = hash_password(data.get('password', ''))

    conn = get_db()
    staff = conn.execute(
        'SELECT * FROM staff WHERE email=? AND password=?', (email, pwd)
    ).fetchone()
    conn.close()

    if not staff:
        return jsonify({'success': False, 'message': 'Invalid email or password'}), 401

    return jsonify({
        'success': True,
        'token':   f'token_{staff["id"]}_{staff["email"]}',
        'user': {
            'id':    staff['id'],
            'name':  staff['name'],
            'email': staff['email'],
            'role':  staff['role'],
        }
    })

# ─────────────────────────────────────────────────────────────
# CLOCK IN
# ─────────────────────────────────────────────────────────────
@app.route('/api/clock-in', methods=['POST'])
def clock_in():
    data     = request.json
    staff_id = data.get('staffId')
    lat      = data.get('latitude')
    lng      = data.get('longitude')
    photo_b64 = data.get('photo', '')  # Base64 photo from frontend
    today    = datetime.date.today().isoformat()
    now      = datetime.datetime.now().strftime('%H:%M:%S')

    # Save photo if provided
    photo_path = None
    if photo_b64:
        try:
            photo_data = base64.b64decode(photo_b64.split(',')[-1])
            photo_path = os.path.join(UPLOAD_FOLDER, f'{staff_id}_{today}.jpg')
            with open(photo_path, 'wb') as f:
                f.write(photo_data)
        except Exception:
            pass

    conn = get_db()

    # Check if already clocked in today
    existing = conn.execute(
        'SELECT * FROM attendance WHERE staff_id=? AND date=?', (staff_id, today)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Already clocked in today'}), 400

    # Save attendance record
    conn.execute('''INSERT INTO attendance
        (staff_id, date, clock_in, clock_in_lat, clock_in_lng, photo)
        VALUES (?,?,?,?,?,?)''',
        (staff_id, today, now, lat, lng, photo_path))
    conn.commit()
    conn.close()

    print(f"✅ Clock IN  — Staff {staff_id} at {now} ({lat}, {lng})")
    return jsonify({'success': True, 'message': 'Clocked in successfully', 'time': now})

# ─────────────────────────────────────────────────────────────
# CLOCK OUT
# ─────────────────────────────────────────────────────────────
@app.route('/api/clock-out', methods=['POST'])
def clock_out():
    data     = request.json
    staff_id = data.get('staffId')
    lat      = data.get('latitude')
    lng      = data.get('longitude')
    today    = datetime.date.today().isoformat()
    now      = datetime.datetime.now().strftime('%H:%M:%S')

    conn = get_db()
    existing = conn.execute(
        'SELECT * FROM attendance WHERE staff_id=? AND date=? AND clock_in IS NOT NULL',
        (staff_id, today)
    ).fetchone()

    if not existing:
        conn.close()
        return jsonify({'success': False, 'message': 'You have not clocked in today'}), 400

    if existing['clock_out']:
        conn.close()
        return jsonify({'success': False, 'message': 'Already clocked out today'}), 400

    conn.execute('''UPDATE attendance
        SET clock_out=?, clock_out_lat=?, clock_out_lng=?
        WHERE staff_id=? AND date=?''',
        (now, lat, lng, staff_id, today))
    conn.commit()
    conn.close()

    print(f"✅ Clock OUT — Staff {staff_id} at {now} ({lat}, {lng})")
    return jsonify({'success': True, 'message': 'Clocked out successfully', 'time': now})

# ─────────────────────────────────────────────────────────────
# LIVE LOCATION UPDATE
# ─────────────────────────────────────────────────────────────
@app.route('/api/location', methods=['POST'])
def update_location():
    data     = request.json
    staff_id = data.get('staffId')
    lat      = data.get('latitude')
    lng      = data.get('longitude')
    now      = datetime.datetime.now().isoformat()

    conn = get_db()
    # Update or insert location
    existing = conn.execute('SELECT id FROM locations WHERE staff_id=?', (staff_id,)).fetchone()
    if existing:
        conn.execute('UPDATE locations SET latitude=?, longitude=?, updated_at=? WHERE staff_id=?',
                     (lat, lng, now, staff_id))
    else:
        conn.execute('INSERT INTO locations (staff_id, latitude, longitude, updated_at) VALUES (?,?,?,?)',
                     (staff_id, lat, lng, now))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─────────────────────────────────────────────────────────────
# GET ATTENDANCE HISTORY (for staff)
# ─────────────────────────────────────────────────────────────
@app.route('/api/attendance/<int:staff_id>', methods=['GET'])
def get_attendance(staff_id):
    conn = get_db()
    records = conn.execute('''
        SELECT a.*, s.name FROM attendance a
        JOIN staff s ON a.staff_id = s.id
        WHERE a.staff_id=? ORDER BY a.date DESC LIMIT 30
    ''', (staff_id,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'records': [dict(r) for r in records]})

# ─────────────────────────────────────────────────────────────
# GET TODAY'S ATTENDANCE (for staff)
# ─────────────────────────────────────────────────────────────
@app.route('/api/attendance/today/<int:staff_id>', methods=['GET'])
def get_today(staff_id):
    today = datetime.date.today().isoformat()
    conn  = get_db()
    record = conn.execute(
        'SELECT * FROM attendance WHERE staff_id=? AND date=?', (staff_id, today)
    ).fetchone()
    conn.close()
    return jsonify({'success': True, 'record': dict(record) if record else None})

# ─────────────────────────────────────────────────────────────
# ADMIN — ALL STAFF
# ─────────────────────────────────────────────────────────────
@app.route('/api/admin/staff', methods=['GET'])
def get_all_staff():
    conn   = get_db()
    staff  = conn.execute('SELECT id, name, email, role, created FROM staff').fetchall()
    conn.close()
    return jsonify({'success': True, 'staff': [dict(s) for s in staff]})

# ─────────────────────────────────────────────────────────────
# ADMIN — ALL ATTENDANCE
# ─────────────────────────────────────────────────────────────
@app.route('/api/admin/attendance', methods=['GET'])
def get_all_attendance():
    date = request.args.get('date', datetime.date.today().isoformat())
    conn = get_db()
    records = conn.execute('''
        SELECT a.*, s.name, s.email FROM attendance a
        JOIN staff s ON a.staff_id = s.id
        WHERE a.date=? ORDER BY a.clock_in DESC
    ''', (date,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'records': [dict(r) for r in records], 'date': date})

# ─────────────────────────────────────────────────────────────
# ADMIN — LIVE LOCATIONS
# ─────────────────────────────────────────────────────────────
@app.route('/api/admin/locations', methods=['GET'])
def get_locations():
    conn = get_db()
    locs = conn.execute('''
        SELECT l.*, s.name FROM locations l
        JOIN staff s ON l.staff_id = s.id
    ''').fetchall()
    conn.close()
    return jsonify({'success': True, 'locations': [dict(l) for l in locs]})

# ─────────────────────────────────────────────────────────────
# ADD NEW STAFF (admin)
# ─────────────────────────────────────────────────────────────
@app.route('/api/admin/staff', methods=['POST'])
def add_staff():
    data = request.json
    try:
        conn = get_db()
        conn.execute('INSERT INTO staff (name, email, password, role) VALUES (?,?,?,?)',
                     (data['name'], data['email'], hash_password(data['password']), data.get('role','staff')))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Staff added successfully'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Email already exists'}), 400

# ─────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    finally:
        s.close()

if __name__ == '__main__':
    init_db()
    ip = get_local_ip()
    print("\n" + "="*50)
    print("  AttendanceApp Backend is running!")
    print("="*50)
    print(f"  API URL: http://{ip}:5000")
    print(f"\n  Demo accounts:")
    print(f"  staff@test.com   / 1234")
    print(f"  priya@test.com   / 1234")
    print(f"  admin@test.com   / admin123")
    print("="*50)
    print("  Press Ctrl+C to stop\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
