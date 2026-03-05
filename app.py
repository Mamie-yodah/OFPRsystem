import os, io, re, time, shutil, csv
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
from datetime import datetime
from functools import wraps
from uuid import uuid4
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    jsonify, abort, send_file, make_response
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required,
    current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from sqlalchemy import text

# Optional dotenv
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

# PDF generation (reportlab required)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change_me_now')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', os.path.join('static','uploads','avatars'))

# Mail config
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASS')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USER')

db = SQLAlchemy(app)
mail = Mail(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def init_database():
    """Initialize database with proper error handling for corruption."""
    try:
        with db.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        db.create_all()
        try:
            ensure_profile_columns()
        except Exception as e:
            print(f"⚠️ Could not ensure profile columns: {e}")
        return True
    except Exception as e:
        print(f"❌ Database error detected: {e}")
        
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        if os.path.exists(db_path):
            print("🔧 Removing corrupted database file...")
            try:
                os.remove(db_path)
                print("✅ Corrupted database removed")
                
                # Try to recreate the database
                db.create_all()
                print("✅ Database recreated successfully")
                return True
            except Exception as recreate_error:
                print(f"❌ Failed to recreate database: {recreate_error}")
                return False
        else:
            print("🔧 Database file not found, creating new one...")
            try:
                db.create_all()
                try:
                    ensure_profile_columns()
                except Exception as e:
                    print(f"⚠️ Could not ensure profile columns: {e}")
                print("✅ New database created successfully")
                return True
            except Exception as create_error:
                print(f"❌ Failed to create database: {create_error}")
                return False

# Models
class Student(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    course_code = db.Column(db.String(64), nullable=False)
    tuition = db.Column(db.Float, nullable=False, default=635.0)
    is_registered_semester = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(128), nullable=True)
    contact_number = db.Column(db.String(32), nullable=True)
    profile_photo = db.Column(db.String(255), nullable=True)  # relative path under static/
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(64), nullable=True)
    session_revoke_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(128), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref='payments')

class PaymentIntent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    reference = db.Column(db.String(128), unique=True, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), default='pending')  # pending/paid
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student')

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class StudentNotice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    notice_id = db.Column(db.Integer, db.ForeignKey('notice.id'), nullable=False)
    viewed = db.Column(db.Boolean, default=False)
    viewed_at = db.Column(db.DateTime)
    student = db.relationship('Student', backref='student_notices')
    notice = db.relationship('Notice', backref='student_notices')

@login_manager.user_loader
def load_user(user_id):
    return Student.query.get(int(user_id))

# Courses
COURSES = {
    "beng": {"name":"Bachelor of Engineering (Honours) in Telecommunications Engineering","tuition":785.0,"duration":"5 years"},
    "dip_se": {"name":"Diploma in Software Engineering","tuition":635.0,"duration":"3 years"},
    "dip_ds": {"name":"Diploma in Data Science","tuition":635.0,"duration":"3 years"},
    "dip_tel": {"name":"Diploma in Telecommunications","tuition":635.0,"duration":"3 years"},
    "dip_dm": {"name":"Diploma in Digital Marketing","tuition":635.0,"duration":"3 years"},
    "dip_cn": {"name":"Diploma in Computer Networking","tuition":635.0,"duration":"3 years"},
    "dip_cy": {"name":"Diploma in Cyber Security","tuition":635.0,"duration":"3 years"},
    "dip_fe": {"name":"Diploma in Financial Engineering","tuition":635.0,"duration":"3 years"},
    "dip_ba": {"name":"Diploma in Business Analytics","tuition":635.0,"duration":"3 years"},
}

ENTRY_REQ = [
    "5 O Level passes including English, Mathematics, and Science",
    "For degree: 3 A Level passes including Mathematics, Physics, and a third science subject",
    "Submit certified copies of results, birth certificate, and national ID"
]

# Helpers and receipts
def receipt_path(student_id, reference):
    # Store receipts in static/receipts/<student_id>_<reference>.pdf
    folder = os.path.join('static', 'receipts')
    if not os.path.exists(folder):
        os.makedirs(folder)
    filename = f"{student_id}_{reference}.pdf"
    return os.path.join(folder, filename)
def current_semester_label():
    now = datetime.utcnow()
    term = "1" if now.month <= 6 else "2"
    return f"{now.year}-{term}"

def send_email(subject, recipients, body, attachments=None):
    try:
        msg = Message(subject, recipients=recipients)
        msg.body = body
        if attachments:
            for attachment in attachments:
                with open(attachment, 'rb') as f:
                    msg.attach(os.path.basename(attachment), 'application/octet-stream', f.read())
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail send error: {e}")
        return False

def ensure_profile_columns():
    """Ensure new Student columns exist when using SQLite by applying simple ALTERs."""
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///'):
        return
    db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///','')
    if not os.path.exists(db_path):
        return
    with db.engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text('PRAGMA table_info(student)')).fetchall()]
        if 'contact_number' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN contact_number VARCHAR(32)'))
            except Exception as e:
                print(f"Ignore contact_number add error: {e}")
        if 'profile_photo' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN profile_photo VARCHAR(255)'))
            except Exception as e:
                print(f"Ignore profile_photo add error: {e}")
        if 'created_at' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN created_at DATETIME'))
            except Exception as e:
                print(f"Ignore created_at add error: {e}")
        if 'last_login_at' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN last_login_at DATETIME'))
            except Exception as e:
                print(f"Ignore last_login_at add error: {e}")
        if 'last_login_ip' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN last_login_ip VARCHAR(64)'))
            except Exception as e:
                print(f"Ignore last_login_ip add error: {e}")
        if 'session_revoke_at' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN session_revoke_at DATETIME'))
            except Exception as e:
                print(f"Ignore session_revoke_at add error: {e}")
        if 'is_active' not in cols:
            try:
                conn.execute(text('ALTER TABLE student ADD COLUMN is_active BOOLEAN DEFAULT 1'))
            except Exception as e:
                print(f"Ignore is_active add error: {e}")

# Simple audit log
class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(150), nullable=False)  # admin email or system
    action = db.Column(db.String(100), nullable=False)
    subject_id = db.Column(db.Integer, nullable=True)
    log_data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def write_audit(actor: str, action: str, subject_id: int | None = None, metadata: str | None = None):
    try:
        log = AuditLog(actor=actor, action=action, subject_id=subject_id, log_data=metadata)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        app.logger.warning('Audit write failed: %s', e)

@app.before_request
def enforce_forced_logout():
    try:
        if current_user and getattr(current_user, 'is_authenticated', False):
            if current_user.is_active is False:
                logout_user()
                flash('Your account has been deactivated by admin.', 'warning')
                return redirect(url_for('login'))
            if current_user.session_revoke_at:
                # If session revoke timestamp is after login time, force logout
                if not current_user.last_login_at or current_user.session_revoke_at >= current_user.last_login_at:
                    logout_user()
                    flash('Your session has been terminated by admin.', 'warning')
                    return redirect(url_for('login'))
    except Exception:
        pass

# Email verification route
@app.route('/verify/<token>')
def verify_email(token):
    s = Student.query.filter_by(verification_token=token).first()
    if not s:
        flash("Invalid or expired verification link.", "error")
        return redirect(url_for('login'))
    s.is_verified = True
    s.verification_token = None
    db.session.commit()
    flash("Email verified! You can now log in.", "success")
    return redirect(url_for('login'))

# Resend verification email
@app.route('/resend_verification', methods=['POST'])
def resend_verification():
    email = (request.form.get('email') or '').strip().lower()
    if not email:
        flash('Please enter your email and click Resend verification again.', 'error')
        return redirect(url_for('login'))
    s = Student.query.filter_by(email=email).first()
    # Use generic messaging to avoid account enumeration
    if not s:
        flash('If an account exists for that email, a verification link has been sent.', 'info')
        return redirect(url_for('login'))
    if s.is_verified:
        flash('Your email is already verified. Please log in.', 'info')
        return redirect(url_for('login'))
    import secrets
    token = secrets.token_urlsafe(32)
    s.verification_token = token
    db.session.commit()
    verify_url = url_for('verify_email', token=token, _external=True)
    send_email("Verify your TCFL account", [s.email], f"Hi {s.full_name},\nPlease verify your email by clicking the link below:\n{verify_url}")
    flash('Verification link sent. Please check your email inbox.', 'success')
    return redirect(url_for('login'))

# PDF fallback if reportlab is not available
def generate_pdf_receipt(student, payment):
    raise RuntimeError("reportlab not available")

# Mock paynow
class MockPayNow:
    def create_payment(self, email, amount, student_name=None, student_id=None):
        import random, time
        ts = int(time.time())
        if student_name and student_id:
            # Make ref descriptive: StudentID_Name_Timestamp
            safe_name = student_name.replace(' ', '_').replace('/', '').replace('\\', '')[:20]  # limit length
            ref = f"{student_id}_{safe_name}_{ts}"
        else:
            ref = f"PN{ts}{random.randint(100,999)}"
        payment_url = f"https://paynow.co.zw/sandbox/pay?email={email}&amount={amount}&ref={ref}"
        return {"ref": ref, "payment_url": payment_url, "poll_url": f"/api/check_payment/{ref}"}

    def check_payment_status(self, ref):
        digits = ''.join([c for c in ref if c.isdigit()])
        if digits and int(digits[-1]) % 2 == 0:
            return {"status": "paid"}
        return {"status": "pending"}

paynow = MockPayNow()

# Routes
@app.route('/')
def index():
    return render_template('index.html', courses=COURSES, entry_req=ENTRY_REQ)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        inquiry_type = request.form.get('inquiry_type')
        message = request.form.get('message')
        send_to = request.form.get('send_to')  # New field from form

        admin_email = os.getenv('ADMIN_EMAIL') or os.getenv('MAIL_USER')
        subject = f"Contact Form: {inquiry_type or 'General Inquiry'}"
        body = f"Name: {full_name}\nEmail: {email}\nPhone: {phone or 'Not provided'}\nInquiry Type: {inquiry_type or 'General'}\n\nMessage:\n{message}"

        # Route message based on send_to
        if send_to == 'email':
            if admin_email and full_name and email and message:
                send_email(subject, [admin_email], body)
        elif send_to == 'phone':
            # Placeholder: Integrate SMS API here (e.g., Twilio)
            # Example: send_sms(phone, body)
            print(f"[SMS] Would send to {phone}: {body}")
        elif send_to == 'whatsapp':
            # Placeholder: Integrate WhatsApp API here (e.g., Twilio WhatsApp)
            # Example: send_whatsapp(phone, body)
            print(f"[WhatsApp] Would send to {phone}: {body}")
        else:
            # Default: send email
            if admin_email and full_name and email and message:
                send_email(subject, [admin_email], body)

        flash('Thanks for your message. We will respond shortly.','success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        step = request.form.get('step')
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        course_code = request.form.get('course_code') or ''

        if step == '1':
            # Step 1 submitted, show Step 2 with pre-filled hidden fields
            return render_template('register.html', courses=COURSES, entry_req=ENTRY_REQ, full_name=full_name, email=email, password=password, step2=True)

        if step == '2':
            # Step 2 submitted, show confirmation step
            return render_template('register.html', courses=COURSES, entry_req=ENTRY_REQ, full_name=full_name, email=email, password=password, course_code=course_code, step3=True)

        if step == '3':
            # Final confirmation: validate and register
            if not full_name or not email or not password or course_code not in COURSES:
                flash("Please fill the form correctly.", "error"); return redirect(url_for('register'))
            if Student.query.filter_by(email=email).first():
                flash("Email already registered.", "error"); return redirect(url_for('register'))
            import secrets
            token = secrets.token_urlsafe(32)
            s = Student(full_name=full_name, email=email, course_code=course_code, tuition=COURSES[course_code]['tuition'], is_verified=False, verification_token=token)
            s.set_password(password)
            db.session.add(s); db.session.commit()
            for n in Notice.query.all():
                sn = StudentNotice(student_id=s.id, notice_id=n.id, viewed=False)
                db.session.add(sn)
            db.session.commit()
            verify_url = url_for('verify_email', token=token, _external=True)
            send_email("Verify your TCFL account", [s.email], f"Hi {s.full_name},\nPlease verify your email by clicking the link below:\n{verify_url}")
            flash("Registered! Please check your email to verify your account before logging in.", "success"); return redirect(url_for('login'))

    # Always return a response for GET or any other case
    return render_template('register.html', courses=COURSES, entry_req=ENTRY_REQ)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        s = Student.query.filter_by(email=email).first()
        if s and s.check_password(password):
            if not s.is_active:
                flash("Your account is deactivated. Please contact support.", "error")
                return redirect(url_for('login'))
            if not s.is_verified:
                flash("Please verify your email before logging in.", "error")
                return redirect(url_for('login'))
            login_user(s)
            try:
                s.last_login_at = datetime.utcnow()
                s.last_login_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                db.session.add(s)
                db.session.commit()
                write_audit(actor='system', action='student_login', subject_id=s.id, metadata=s.email)
            except Exception as e:
                app.logger.warning("Failed to record last login: %s", e)
            # flash unread notices (not mark viewed yet)
            unread = StudentNotice.query.filter_by(student_id=s.id, viewed=False).join(Notice).all()
            for sn in unread:
                flash(f"NOTICE: {sn.notice.title} — {sn.notice.message}", "info")
            return redirect(url_for('dashboard'))
        flash("Invalid credentials.", "error"); return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); flash("Logged out.", "info"); return redirect(url_for('index'))

@app.route('/student/dashboard')
@login_required
def dashboard():
    sem = current_semester_label()
    total_paid = sum(p.amount for p in current_user.payments)
    min_required = 0.6*(current_user.tuition or 0)
    status_ok = total_paid >= min_required
    # mark unread notices as viewed now that dashboard displayed
    unread = StudentNotice.query.filter_by(student_id=current_user.id, viewed=False).all()
    for sn in unread:
        sn.viewed = True
        sn.viewed_at = datetime.utcnow()
        db.session.add(sn)
    db.session.commit()
    all_notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template('dashboard.html',
        semester=sem,
        total_paid=total_paid,
        min_required=min_required,
        status_ok=status_ok,
        course=COURSES.get(current_user.course_code),
        all_notices=all_notices
    )

@app.route('/student/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST':
        full_name=(request.form.get('full_name') or '').strip()
        course_code=request.form.get('course_code') or current_user.course_code
        contact_number=(request.form.get('contact_number') or '').strip()
        if not full_name or course_code not in COURSES:
            flash("Invalid input.", "error"); return redirect(url_for('profile'))
        # Program change guard if 60% reached
        if course_code!=current_user.course_code and sum(p.amount for p in current_user.payments) >= 0.6*(current_user.tuition or 0):
            flash("Cannot change program after reaching 60% threshold.", "warning"); return redirect(url_for('profile'))
        current_user.full_name=full_name
        current_user.contact_number=contact_number or None
        if course_code!=current_user.course_code:
            current_user.course_code=course_code
            current_user.tuition=COURSES[course_code]['tuition']

        # Handle profile photo upload
        try:
            file = request.files.get('profile_photo')
            if file and file.filename:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                filename = secure_filename(f"{current_user.id}_{int(time.time())}_{file.filename}")
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                # Store relative path under static/
                rel_path = save_path.replace('static'+os.sep, '').replace('static/', '')
                current_user.profile_photo = rel_path
        except Exception as e:
            app.logger.warning("Avatar upload failed: %s", e)

        db.session.commit(); flash("Profile updated.", "success"); return redirect(url_for('dashboard'))
    return render_template('profile.html', student=current_user, courses=COURSES, entry_req=ENTRY_REQ)

@app.route('/student/status')
@login_required
def status():
    sem=current_semester_label()
    total_paid=sum(p.amount for p in current_user.payments)
    min_required=0.6*(current_user.tuition or 0)
    is_ok = total_paid>=min_required
    return render_template('status.html', semester=sem, is_ok=is_ok, total_paid=total_paid, min_required=min_required, tuition=current_user.tuition, course=COURSES.get(current_user.course_code))

@app.route('/student/payment')
@login_required
def payment():
    return render_template('payment.html', tuition=current_user.tuition)

@app.route('/api/create_payment', methods=['POST'])
@login_required
def api_create_payment():
    data=request.get_json() or {}
    try: amount=float(data.get('amount') or 0)
    except: amount=0.0
    if amount<=0: return jsonify({"error":"Invalid amount"}),400
    # Use school's email for payments, so all go to one account
    school_email = os.getenv('SCHOOL_EMAIL', 'school@tcfl.edu.zw')  # or ADMIN_EMAIL
    resp=paynow.create_payment(school_email, amount, student_name=current_user.full_name, student_id=current_user.id)
    ref=resp['ref']; payment_url=resp['payment_url']
    intent=PaymentIntent(student_id=current_user.id, reference=ref, amount=amount, status='pending')
    db.session.add(intent); db.session.commit()
    return jsonify({"ref":ref,"payment_url":payment_url})

@app.route('/api/check_payment/<ref>')
@login_required
def api_check_payment(ref):
    status=paynow.check_payment_status(ref)
    intent=PaymentIntent.query.filter_by(reference=ref, student_id=current_user.id).first()
    if not intent: return jsonify({"error":"Unknown ref"}),404
    if status.get('status')=='paid' and intent.status!='paid':
        intent.status='paid'; db.session.add(intent)
        p = Payment(student_id=current_user.id, amount=intent.amount, reference=intent.reference)
        db.session.add(p); db.session.commit()
        total_paid=sum(pp.amount for pp in current_user.payments)
        is_ok = total_paid>=0.6*(current_user.tuition or 0)
        current_user.is_registered_semester = is_ok
        db.session.add(current_user); db.session.commit()
        # generate pdf and email
        try:
            if REPORTLAB_AVAILABLE and p:
                pdf_path=generate_pdf_receipt(current_user, p)
                with open(pdf_path,'rb') as fh: pdf_bytes=fh.read()
                send_email("Payment Receipt - TCFL",[current_user.email],f"Hi {current_user.full_name},\\nAttached receipt.",attachments=[(os.path.basename(pdf_path),'application/pdf',pdf_bytes)])
        except Exception as e:
            app.logger.warning("Receipt/email failed: %s",e)
        admin_email=os.getenv('ADMIN_EMAIL') or os.getenv('MAIL_USER')
        if admin_email:
            send_email("Student Payment Notification - TCFL",[admin_email],f"{current_user.full_name} paid US${intent.amount:.2f}. Total: US${total_paid:.2f}. Registered: {'Yes' if is_ok else 'No'}")
        return jsonify({"status":"paid","total_paid":total_paid,"registered":is_ok})
    return jsonify(status)

@app.route('/download_receipt/<int:payment_id>')
@login_required
def download_receipt(payment_id):
    p=Payment.query.get(payment_id)
    if not p: abort(404)
    if p.student_id!=current_user.id: abort(403)
    path=receipt_path(p.student_id,p.reference)
    if not os.path.exists(path):
        if REPORTLAB_AVAILABLE:
            generate_pdf_receipt(current_user,p)
        else:
            abort(500,"PDF support not installed on server")
    return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype='application/pdf')

# Admin features
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        email=(request.form.get('email') or '').strip().lower()
        password=request.form.get('password') or ''
        # Debug: print loaded env values
        print(f"[DEBUG] Loaded ADMIN_EMAIL: {os.getenv('ADMIN_EMAIL')}")
        print(f"[DEBUG] Loaded ADMIN_PASSWORD: {os.getenv('ADMIN_PASSWORD')}")
        print(f"[DEBUG] Submitted email: {email}")
        print(f"[DEBUG] Submitted password: {password}")
        if email== (os.getenv('ADMIN_EMAIL') or '').lower() and password== (os.getenv('ADMIN_PASSWORD') or ''):
            session['admin_logged_in']=True; return redirect(url_for('admin_dashboard'))
        flash("Invalid admin credentials","error"); return redirect(url_for('admin_login'))
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in',None); flash("Admin logged out","info"); return redirect(url_for('admin_login'))

def admin_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return inner

@app.route('/admin')
@admin_required
def admin_dashboard():
    sem = current_semester_label()
    students = Student.query.all()
    total_students = len(students)
    registered_students = sum(1 for s in students if sum(p.amount for p in s.payments) >= 0.6*(s.tuition or 0))
    total_payments = sum(p.amount for s in students for p in s.payments)
    rows = []
    for s in students:
        total_paid = sum(p.amount for p in s.payments)
        rows.append({
            "id": s.id,
            "name": s.full_name,
            "email": s.email,
            "course": COURSES.get(s.course_code, {}).get("name", s.course_code),
            "tuition": s.tuition,
            "total_paid": total_paid,
            "registered": total_paid >= 0.6*(s.tuition or 0)
        })
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    recent_notices = Notice.query.order_by(Notice.created_at.desc()).limit(5).all()
    recent_students = Student.query.order_by(Student.created_at.desc()).limit(10).all()
    recent_logins = Student.query.filter(Student.last_login_at.isnot(None)).order_by(Student.last_login_at.desc()).limit(10).all()
    return render_template('admin_dashboard.html',
        semester=sem,
        rows=rows,
        total_students=total_students,
        registered_students=registered_students,
        total_payments=total_payments,
        recent_payments=recent_payments,
        recent_notices=recent_notices,
        recent_students=recent_students,
        recent_logins=recent_logins
    )

# Admin: Students list and search
@app.route('/admin/students')
@admin_required
def admin_students():
    q = (request.args.get('q') or '').strip().lower()
    query = Student.query
    if q:
        like = f"%{q}%"
        query = query.filter((Student.full_name.ilike(like)) | (Student.email.ilike(like)))
    students = query.order_by(Student.full_name).all()
    return render_template('admin_students.html', students=students, q=q, courses=COURSES)

# Admin: Edit a student
@app.route('/admin/students/<int:student_id>', methods=['GET','POST'])
@admin_required
def admin_student_edit(student_id):
    s = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        course_code = request.form.get('course_code') or s.course_code
        contact_number = (request.form.get('contact_number') or '').strip()
        is_verified = True if request.form.get('is_verified') == 'on' else False
        if not full_name or not email or course_code not in COURSES:
            flash('Please provide valid name, email, and program.', 'error'); return redirect(url_for('admin_student_edit', student_id=student_id))
        # Check email uniqueness
        existing = Student.query.filter(Student.email==email, Student.id!=s.id).first()
        if existing:
            flash('Email already in use by another account.', 'error'); return redirect(url_for('admin_student_edit', student_id=student_id))
        s.full_name = full_name
        s.email = email
        s.contact_number = contact_number or None
        if course_code != s.course_code:
            s.course_code = course_code
            s.tuition = COURSES[course_code]['tuition']
        s.is_verified = is_verified
        db.session.commit()
        write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='student_update', subject_id=s.id, metadata=s.email)
        flash('Student updated.', 'success'); return redirect(url_for('admin_students'))
    return render_template('admin_student_edit.html', student=s, courses=COURSES)

# Admin: Reset password
@app.route('/admin/students/<int:student_id>/reset_password', methods=['POST'])
@admin_required
def admin_student_reset_password(student_id):
    s = Student.query.get_or_404(student_id)
    new_password = (request.form.get('new_password') or '').strip()
    if len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'error'); return redirect(url_for('admin_student_edit', student_id=student_id))
    s.set_password(new_password)
    db.session.commit()
    write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='student_password_reset', subject_id=s.id)
    flash('Password reset successfully.', 'success'); return redirect(url_for('admin_student_edit', student_id=student_id))

# Admin: Force logout
@app.route('/admin/students/<int:student_id>/force_logout', methods=['POST'])
@admin_required
def admin_student_force_logout(student_id):
    s = Student.query.get_or_404(student_id)
    s.session_revoke_at = datetime.utcnow()
    db.session.commit()
    write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='student_force_logout', subject_id=s.id)
    flash('Student sessions revoked. They will be logged out on next request.', 'success')
    return redirect(url_for('admin_student_edit', student_id=student_id))

# Admin: Bulk actions and export
@app.route('/admin/students/bulk', methods=['POST'])
@admin_required
def admin_students_bulk():
    action = request.form.get('action')
    ids = request.form.getlist('ids')
    students = Student.query.filter(Student.id.in_(ids)).all() if ids else []
    count = 0
    if action == 'verify':
        for s in students:
            if not s.is_verified:
                s.is_verified = True; count += 1
        db.session.commit(); write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='bulk_verify', metadata=str(ids))
        flash(f'Verified {count} students.', 'success')
    elif action == 'deactivate':
        for s in students:
            if s.is_active:
                s.is_active = False; count += 1
        db.session.commit(); write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='bulk_deactivate', metadata=str(ids))
        flash(f'Deactivated {count} students.', 'success')
    elif action == 'reactivate':
        for s in students:
            if not s.is_active:
                s.is_active = True; count += 1
        db.session.commit(); write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='bulk_reactivate', metadata=str(ids))
        flash(f'Reactivated {count} students.', 'success')
    elif action == 'export':
        # Simple CSV export of selected students
        si = io.StringIO(); cw = csv.writer(si)
        cw.writerow(['ID','Name','Email','Program','Verified','Active'])
        for s in students:
            cw.writerow([s.id, s.full_name, s.email, COURSES.get(s.course_code,{}).get('name', s.course_code), 'Yes' if s.is_verified else 'No', 'Yes' if s.is_active else 'No'])
        output = make_response(si.getvalue())
        output.headers['Content-Disposition'] = 'attachment; filename=students_export.csv'
        output.headers['Content-type'] = 'text/csv'
        write_audit(actor=session.get('ADMIN_EMAIL') or 'admin', action='bulk_export', metadata=str(ids))
        return output
    else:
        flash('Unknown action.', 'error')
    return redirect(url_for('admin_students'))

# Admin: Audit logs page
@app.route('/admin/audit')
@admin_required
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template('admin_audit.html', logs=logs)

@app.route('/admin/notice', methods=['GET','POST'])
@admin_required
def admin_notice():
    if request.method=='POST':
        title=(request.form.get('title') or '').strip()
        message=(request.form.get('message') or '').strip()
        if not title or not message:
            flash("Please provide title and message","error"); return redirect(url_for('admin_notice'))
        n = Notice(title=title, message=message)
        db.session.add(n); db.session.commit()
        for s in Student.query.all():
            sn = StudentNotice(student_id=s.id, notice_id=n.id, viewed=False)
            db.session.add(sn)
        db.session.commit()
        flash("Notice sent to all students.","success"); return redirect(url_for('admin_dashboard'))
    return render_template('admin_notice.html')

@app.route('/admin/report')
@admin_required
def admin_report():
    # Generate CSV report of students and payments
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Student ID","Full Name","Email","Program","Tuition","Total Paid","Registered"])
    for s in Student.query.order_by(Student.full_name).all():
        total_paid = sum(p.amount for p in s.payments)
        registered = "Yes" if total_paid >= 0.6*(s.tuition or 0) else "No"
        cw.writerow([s.id, s.full_name, s.email, COURSES.get(s.course_code,{}).get("name",s.course_code), f"{s.tuition:.2f}", f"{total_paid:.2f}", registered])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=payment_report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# Init DB and seed mock students if empty
with app.app_context():
    if init_database():
        if Student.query.count() == 0:
            print("📝 Creating default test accounts...")
            s1 = Student(full_name="John Doe", email="john@example.com", course_code="dip_se", tuition=COURSES["dip_se"]["tuition"])
            s1.set_password("Password123")
            s2 = Student(full_name="Jane Smith", email="jane@example.com", course_code="beng", tuition=COURSES["beng"]["tuition"])
            s2.set_password("Password123")
            # Mark default test accounts as verified for immediate access
            s1.is_verified = True
            s2.is_verified = True
            db.session.add_all([s1,s2])
            db.session.commit()
            
             #If admin created notices before, ensure studentnotice entries exist
            for n in Notice.query.all():
                for s in [s1,s2]:
                    if not StudentNotice.query.filter_by(student_id=s.id, notice_id=n.id).first():
                        db.session.add(StudentNotice(student_id=s.id, notice_id=n.id, viewed=False))
            db.session.commit()
            print("✅ Default accounts created successfully!")
            print("   - john@example.com / Password123")
            print("   - jane@example.com / Password123")
    else:
        print("❌ Cannot start application due to database issues.")
        print("🔧 Please run: python scripts/reset_database.py")
        exit(1)

if __name__=='__main__':
    app.run(debug=True)
