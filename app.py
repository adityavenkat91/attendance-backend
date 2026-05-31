from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, hashlib, os, base64, datetime, json

app = Flask(__name__)
CORS(app)

DB_FILE       = 'attendance.db'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '',
        password TEXT NOT NULL,
        role TEXT DEFAULT 'staff',
        face_descriptor TEXT DEFAULT NULL,
        face_photo TEXT DEFAULT NULL,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        clock_in TEXT,
        clock_out TEXT,
        clock_in_lat REAL,
        clock_in_lng REAL,
        clock_out_lat REAL,
        clock_out_lng REAL,
        status TEXT DEFAULT 'present'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        latitude REAL,
        longitude REAL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    try: c.execute('ALTER TABLE staff ADD COLUMN employee_id TEXT')
    except: pass
    try: c.execute('ALTER TABLE staff ADD COLUMN phone TEXT DEFAULT ""')
    except: pass
    try: c.execute('ALTER TABLE staff ADD COLUMN face_descriptor TEXT DEFAULT NULL')
    except: pass
    try: c.execute('ALTER TABLE staff ADD COLUMN face_photo TEXT DEFAULT NULL')
    except: pass
    demo = [
        ('EMP001','Rahul Kumar','staff@test.com','9876543210',hash_password('1234'),'staff'),
        ('EMP002','Priya Sharma','priya@test.com','9876543211',hash_password('1234'),'staff'),
        ('EMP003','Admin User','admin@test.com','9876543212',hash_password('admin123'),'admin'),
    ]
    for eid,name,email,phone,pwd,role in demo:
        try:
            c.execute('INSERT INTO staff (employee_id,name,email,phone,password,role) VALUES (?,?,?,?,?,?)',
                      (eid,name,email,phone,pwd,role))
        except: pass
    staff_no_id = conn.execute('SELECT id FROM staff WHERE employee_id IS NULL').fetchall()
    count = conn.execute('SELECT COUNT(*) as c FROM staff').fetchone()['c']
    for i, s in enumerate(staff_no_id):
        conn.execute('UPDATE staff SET employee_id=? WHERE id=?', (f'EMP{str(count+i+1).zfill(3)}', s['id']))
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return jsonify({'status': 'AttendanceApp API running', 'version': '2.0'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    login_id = data.get('email','').strip()
    pwd = hash_password(data.get('password',''))
    conn = get_db()
    staff = conn.execute(
        'SELECT * FROM staff WHERE (email=? OR employee_id=?) AND password=?',
        (login_id, login_id.upper(), pwd)
    ).fetchone()
    conn.close()
    if not staff:
        return jsonify({'success':False,'message':'Invalid credentials'}), 401
    return jsonify({'success':True,'token':f'token_{staff["id"]}',
        'user':{'id':staff['id'],'name':staff['name'],'email':staff['email'],
                'role':staff['role'],'employee_id':staff['employee_id'],
                'phone':staff['phone'] or '','face_enrolled':staff['face_descriptor'] is not None}})

@app.route('/api/staff/<int:staff_id>/profile')
def get_profile(staff_id):
    conn = get_db()
    staff = conn.execute('SELECT id,employee_id,name,email,phone,role,created FROM staff WHERE id=?',(staff_id,)).fetchone()
    conn.close()
    if not staff: return jsonify({'success':False}), 404
    return jsonify({'success':True,'user':dict(staff)})

@app.route('/api/staff/<int:staff_id>/edit', methods=['PUT'])
def edit_profile(staff_id):
    data = request.json
    name = data.get('name','').strip()
    phone = data.get('phone','').strip()
    if not name: return jsonify({'success':False,'message':'Name is required'}), 400
    conn = get_db()
    conn.execute('UPDATE staff SET name=?,phone=? WHERE id=?',(name,phone,staff_id))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Profile updated!'})

@app.route('/api/staff/<int:staff_id>/change-password', methods=['POST'])
def change_password(staff_id):
    data = request.json
    cur = hash_password(data.get('current',''))
    new = hash_password(data.get('new',''))
    conn = get_db()
    staff = conn.execute('SELECT password FROM staff WHERE id=?',(staff_id,)).fetchone()
    if not staff or staff['password'] != cur:
        conn.close()
        return jsonify({'success':False,'message':'Current password incorrect'}), 400
    conn.execute('UPDATE staff SET password=? WHERE id=?',(new,staff_id))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Password changed!'})

@app.route('/api/staff/<int:staff_id>/enroll-face', methods=['POST'])
def enroll_face(staff_id):
    data = request.json
    descriptor = data.get('descriptor')
    photo_b64 = data.get('photo','')
    if not descriptor:
        return jsonify({'success':False,'message':'No face detected'}), 400
    photo_path = None
    if photo_b64:
        try:
            photo_data = base64.b64decode(photo_b64.split(',')[-1])
            photo_path = os.path.join(UPLOAD_FOLDER, f'face_{staff_id}.jpg')
            with open(photo_path,'wb') as f: f.write(photo_data)
        except: pass
    conn = get_db()
    conn.execute('UPDATE staff SET face_descriptor=?,face_photo=? WHERE id=?',
                 (json.dumps(descriptor),photo_path,staff_id))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Face enrolled!'})

@app.route('/api/staff/<int:staff_id>/face-descriptor')
def get_face_descriptor(staff_id):
    conn = get_db()
    staff = conn.execute('SELECT face_descriptor FROM staff WHERE id=?',(staff_id,)).fetchone()
    conn.close()
    if not staff or not staff['face_descriptor']:
        return jsonify({'success':False,'message':'No face enrolled'}), 404
    return jsonify({'success':True,'descriptor':json.loads(staff['face_descriptor'])})

@app.route('/api/clock-in', methods=['POST'])
def clock_in():
    data = request.json
    staff_id = data.get('staffId')
    today = datetime.date.today().isoformat()
    now = datetime.datetime.now().strftime('%H:%M:%S')
    conn = get_db()
    if conn.execute('SELECT id FROM attendance WHERE staff_id=? AND date=?',(staff_id,today)).fetchone():
        conn.close()
        return jsonify({'success':False,'message':'Already clocked in today'}), 400
    conn.execute('INSERT INTO attendance (staff_id,date,clock_in,clock_in_lat,clock_in_lng) VALUES (?,?,?,?,?)',
                 (staff_id,today,now,data.get('latitude'),data.get('longitude')))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Clocked in!','time':now})

@app.route('/api/clock-out', methods=['POST'])
def clock_out():
    data = request.json
    staff_id = data.get('staffId')
    today = datetime.date.today().isoformat()
    now = datetime.datetime.now().strftime('%H:%M:%S')
    conn = get_db()
    existing = conn.execute('SELECT id FROM attendance WHERE staff_id=? AND date=? AND clock_in IS NOT NULL',(staff_id,today)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success':False,'message':'Not clocked in today'}), 400
    conn.execute('UPDATE attendance SET clock_out=?,clock_out_lat=?,clock_out_lng=? WHERE staff_id=? AND date=?',
                 (now,data.get('latitude'),data.get('longitude'),staff_id,today))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Clocked out!','time':now})

@app.route('/api/location', methods=['POST'])
def update_location():
    data = request.json
    staff_id = data.get('staffId')
    now = datetime.datetime.now().isoformat()
    conn = get_db()
    if conn.execute('SELECT id FROM locations WHERE staff_id=?',(staff_id,)).fetchone():
        conn.execute('UPDATE locations SET latitude=?,longitude=?,updated_at=? WHERE staff_id=?',
                     (data.get('latitude'),data.get('longitude'),now,staff_id))
    else:
        conn.execute('INSERT INTO locations (staff_id,latitude,longitude,updated_at) VALUES (?,?,?,?)',
                     (staff_id,data.get('latitude'),data.get('longitude'),now))
    conn.commit()
    conn.close()
    return jsonify({'success':True})

@app.route('/api/attendance/<int:staff_id>')
def get_attendance(staff_id):
    conn = get_db()
    records = conn.execute('''SELECT a.*,s.name,s.email,s.employee_id FROM attendance a
        JOIN staff s ON a.staff_id=s.id WHERE a.staff_id=? ORDER BY a.date DESC LIMIT 30''',(staff_id,)).fetchall()
    conn.close()
    return jsonify({'success':True,'records':[dict(r) for r in records]})

@app.route('/api/attendance/today/<int:staff_id>')
def get_today(staff_id):
    today = datetime.date.today().isoformat()
    conn = get_db()
    r = conn.execute('SELECT * FROM attendance WHERE staff_id=? AND date=?',(staff_id,today)).fetchone()
    conn.close()
    return jsonify({'success':True,'record':dict(r) if r else None})

@app.route('/api/admin/staff', methods=['GET'])
def get_all_staff():
    conn = get_db()
    staff = conn.execute('SELECT id,employee_id,name,email,phone,role,created FROM staff').fetchall()
    conn.close()
    return jsonify({'success':True,'staff':[dict(s) for s in staff]})

@app.route('/api/admin/staff', methods=['POST'])
def add_staff():
    data = request.json
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) as c FROM staff').fetchone()['c']
    eid = f'EMP{str(count+1).zfill(3)}'
    try:
        conn.execute('INSERT INTO staff (employee_id,name,email,phone,password,role) VALUES (?,?,?,?,?,?)',
                     (eid,data['name'],data['email'],data.get('phone',''),hash_password(data['password']),data.get('role','staff')))
        conn.commit()
        conn.close()
        return jsonify({'success':True,'message':f'Staff added! Employee ID: {eid}','employee_id':eid})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success':False,'message':'Email already exists'}), 400

@app.route('/api/admin/staff/<int:staff_id>', methods=['PUT'])
def admin_edit_staff(staff_id):
    data = request.json
    conn = get_db()
    staff = conn.execute('SELECT * FROM staff WHERE id=?',(staff_id,)).fetchone()
    if not staff:
        conn.close()
        return jsonify({'success':False,'message':'Staff not found'}), 404
    try:
        conn.execute('UPDATE staff SET name=?,email=?,phone=?,role=? WHERE id=?',
                     (data.get('name',staff['name']),data.get('email',staff['email']),
                      data.get('phone',staff['phone'] or ''),data.get('role',staff['role']),staff_id))
        if data.get('password'):
            conn.execute('UPDATE staff SET password=? WHERE id=?',(hash_password(data['password']),staff_id))
        conn.commit()
        conn.close()
        return jsonify({'success':True,'message':'Staff updated!'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success':False,'message':'Email already exists'}), 400

@app.route('/api/admin/staff/<int:staff_id>', methods=['DELETE'])
def delete_staff(staff_id):
    conn = get_db()
    if not conn.execute('SELECT id FROM staff WHERE id=?',(staff_id,)).fetchone():
        conn.close()
        return jsonify({'success':False,'message':'Staff not found'}), 404
    conn.execute('DELETE FROM attendance WHERE staff_id=?',(staff_id,))
    conn.execute('DELETE FROM locations WHERE staff_id=?',(staff_id,))
    conn.execute('DELETE FROM staff WHERE id=?',(staff_id,))
    conn.commit()
    conn.close()
    return jsonify({'success':True,'message':'Staff deleted!'})

@app.route('/api/admin/attendance')
def get_all_attendance():
    date = request.args.get('date',datetime.date.today().isoformat())
    conn = get_db()
    records = conn.execute('''SELECT a.*,s.name,s.email,s.employee_id FROM attendance a
        JOIN staff s ON a.staff_id=s.id WHERE a.date=? ORDER BY a.clock_in DESC''',(date,)).fetchall()
    conn.close()
    return jsonify({'success':True,'records':[dict(r) for r in records],'date':date})

@app.route('/api/admin/locations')
def get_locations():
    conn = get_db()
    locs = conn.execute('SELECT l.*,s.name,s.employee_id FROM locations l JOIN staff s ON l.staff_id=s.id').fetchall()
    conn.close()
    return jsonify({'success':True,'locations':[dict(l) for l in locs]})

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0',port=port)
