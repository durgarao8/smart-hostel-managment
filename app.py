import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "lab_project_2026"

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect('hostel.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            room_number TEXT,
            email TEXT,
            category TEXT,
            issue TEXT,
            status TEXT DEFAULT 'Pending',
            priority TEXT DEFAULT 'Normal',
            photo TEXT,
            assigned_worker TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deadline TIMESTAMP,
            resolved_at TIMESTAMP,
            escalated INTEGER DEFAULT 0,
            warden_note TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT,
            active INTEGER DEFAULT 1
        )''')
        cur = conn.execute("SELECT COUNT(*) FROM workers")
        if cur.fetchone()[0] == 0:
            conn.executemany("INSERT INTO workers (name, department) VALUES (?, ?)", [
                ("Raju (Electrician)", "Electricity"),
                ("Suresh (Plumber)", "Water/Plumbing"),
                ("Venkat (Maintenance)", "Maintenance"),
                ("Lakshmi (Cleaning)", "Cleanliness"),
                ("Prasad (General)", "General"),
            ])

def check_escalations():
    with get_db() as conn:
        conn.execute("""
            UPDATE complaints SET escalated=1, status='Escalated'
            WHERE status NOT IN ('Resolved','Escalated')
            AND deadline IS NOT NULL AND deadline < datetime('now')
        """)

@app.route('/')
def index():
    return redirect(url_for('student_portal'))

@app.route('/student')
def student_portal():
    return render_template('complaint_form.html')

@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name','').strip()
    room = request.form.get('room_number','').strip()
    email = request.form.get('email','').strip()
    cat = request.form.get('category','General')
    msg = request.form.get('message','').strip()
    priority = request.form.get('priority','Normal')
    filename = None
    file = request.files.get('photo')
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    deadline = datetime.now() + timedelta(days=2)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO complaints (name,room_number,email,category,issue,status,priority,photo,deadline) VALUES (?,?,?,?,?,'Pending',?,?,?)",
            (name, room, email, cat, msg, priority, filename, deadline)
        )
        complaint_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return render_template('submitted.html', complaint_id=complaint_id, name=name)

@app.route('/track')
def track():
    complaint_id = request.args.get('id')
    complaint = None
    if complaint_id:
        with get_db() as conn:
            complaint = conn.execute("SELECT * FROM complaints WHERE id=?", (complaint_id,)).fetchone()
    return render_template('track.html', complaint=complaint, searched=bool(complaint_id))

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == "admin" and request.form['password'] == "warden123":
            session['logged_in'] = True
            return redirect(url_for('warden'))
        error = "Invalid credentials. Try again."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/warden')
def warden():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    check_escalations()
    status_filter = request.args.get('status','all')
    category_filter = request.args.get('category','all')
    with get_db() as conn:
        query = "SELECT * FROM complaints"
        conditions, params = [], []
        if status_filter != 'all':
            conditions.append("status=?"); params.append(status_filter)
        if category_filter != 'all':
            conditions.append("category=?"); params.append(category_filter)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY submitted_at DESC"
        data = conn.execute(query, params).fetchall()
        stats = {
            'pending':     conn.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0],
            'in_progress': conn.execute("SELECT COUNT(*) FROM complaints WHERE status='In Progress'").fetchone()[0],
            'resolved':    conn.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
            'escalated':   conn.execute("SELECT COUNT(*) FROM complaints WHERE status='Escalated'").fetchone()[0],
        }
        workers = conn.execute("SELECT * FROM workers WHERE active=1").fetchall()
        categories = conn.execute("SELECT DISTINCT category FROM complaints").fetchall()
    return render_template('warden.html', complaints=data, stats=stats,
                           workers=workers, categories=categories,
                           status_filter=status_filter, category_filter=category_filter)

@app.route('/resolve/<int:id>')
def resolve(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    with get_db() as conn:
        conn.execute("UPDATE complaints SET status='Resolved', resolved_at=datetime('now') WHERE id=?", (id,))
    return redirect(url_for('warden'))

@app.route('/assign/<int:id>', methods=['POST'])
def assign(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    worker = request.form.get('worker')
    note = request.form.get('warden_note','')
    with get_db() as conn:
        conn.execute("UPDATE complaints SET assigned_worker=?, status='In Progress', warden_note=? WHERE id=?",
                     (worker, note, id))
    return redirect(url_for('warden'))

@app.route('/delete/<int:id>')
def delete_complaint(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    with get_db() as conn:
        row = conn.execute("SELECT photo FROM complaints WHERE id=?", (id,)).fetchone()
        if row and row['photo']:
            try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], row['photo']))
            except: pass
        conn.execute("DELETE FROM complaints WHERE id=?", (id,))
    return redirect(url_for('warden'))

@app.route('/analytics')
def analytics():
    if not session.get('logged_in'): return redirect(url_for('login'))
    with get_db() as conn:
        by_category = conn.execute("SELECT category, COUNT(*) as count FROM complaints GROUP BY category").fetchall()
        by_status   = conn.execute("SELECT status, COUNT(*) as count FROM complaints GROUP BY status").fetchall()
        by_priority = conn.execute("SELECT priority, COUNT(*) as count FROM complaints GROUP BY priority").fetchall()
        recent      = conn.execute("SELECT DATE(submitted_at) as day, COUNT(*) as count FROM complaints GROUP BY day ORDER BY day DESC LIMIT 14").fetchall()
        avg_res     = conn.execute("SELECT AVG((julianday(resolved_at)-julianday(submitted_at))*24) as avg_hours FROM complaints WHERE resolved_at IS NOT NULL").fetchone()
    return render_template('analytics.html', by_category=by_category, by_status=by_status,
                           by_priority=by_priority, recent=recent, avg_resolution=avg_res)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
