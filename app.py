from flask import Flask, render_template, request, redirect, session, send_file
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from datetime import datetime
import os, uuid
from io import BytesIO
from cryptography.fernet import Fernet
import hashlib
from flask import flash
import hashlib
import os
import uuid
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from werkzeug.utils import secure_filename
from flask import flash, redirect, request, session
from fpdf import FPDF
from PIL import Image
import io
from docx import Document

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# MongoDB setup
client = MongoClient("mongodb://localhost:27017/")
db = client['secure_file_manager']
users_col = db['users']
files_col = db['files']


# --- Persistent Encryption Key ---
KEY_FILE = 'fernet.key'
if os.path.exists(KEY_FILE):
    with open(KEY_FILE, 'rb') as f:
        fernet_key = f.read()
else:
    fernet_key = Fernet.generate_key()
    with open(KEY_FILE, 'wb') as f:
        f.write(fernet_key)

fernet = Fernet(fernet_key)

# Upload folder
UPLOAD_FOLDER = 'uploaded_files'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ================== ROUTES ==================

@app.route('/')
def home():
    return redirect('/login')

# --- SIGNUP ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if users_col.find_one({'email': email}):
            return render_template('message.html', message='Email already registered.')
        users_col.insert_one({'email': email, 'password': password})
        return render_template('message.html', message='Signup successful! Please login.')
    return render_template('signup.html')

# --- LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = users_col.find_one({'email': email, 'password': password})
        if user:
            session['user'] = email
            return redirect('/dashboard')
        return render_template('message.html', message='Invalid credentials.')
    return render_template('login.html')

# --- DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')
    files = list(files_col.find({'owner': session['user']}))
    for f in files:
        f['upload_time'] = f.get('upload_time', datetime.utcnow())
        filepath = os.path.join(UPLOAD_FOLDER, f['unique_id'])
        f['file_size'] = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    return render_template('dashboard.html', files=files)

# --- UPLOAD ---
@app.route('/upload', methods=['POST'])
def upload():
    if 'user' not in session:
        return redirect('/login')

    file = request.files.get('file')
    custom_name = request.form.get('custom_name')

    if not file or file.filename.strip() == '':
        flash('⚠️ No file selected!', 'error')
        return redirect('/dashboard')

    original_filename = secure_filename(file.filename)
    ext = os.path.splitext(original_filename)[1].lower()

    # Final filename generate
    if custom_name and custom_name.strip():
        filename_to_store = secure_filename(custom_name.strip()).lower() + ext
    else:
        filename_to_store = original_filename.lower()

    # SAME NAME CHECK
    existing_name = files_col.find_one({
        'filename': filename_to_store.lower(),
        'owner': session['user']
    })
    if existing_name:
        flash('⚠️ A file with the same name already exists!', 'error')
        return redirect('/dashboard')

    # Read content
    content = file.read()
    file.seek(0)

    if not content:
        flash('⚠️ Empty file!', 'error')
        return redirect('/dashboard')

    # SAME CONTENT CHECK
    file_hash = hashlib.sha256(content).hexdigest()
    existing_content = files_col.find_one({
        'file_hash': file_hash,
        'owner': session['user']
    })
    if existing_content:
        flash('⚠️ This exact file already exists!', 'error')
        return redirect('/dashboard')

    # Encrypt & save file
    encrypted = fernet.encrypt(content)
    unique_id = str(uuid.uuid4())
    filepath = os.path.join(UPLOAD_FOLDER, unique_id)
    with open(filepath, 'wb') as f:
        f.write(encrypted)

    # 🔹 New field added for stored filename reference
    doc = {
        'owner': session['user'],
        'filename': filename_to_store.lower(),
        'stored_filename': unique_id,     # actual stored file name
        'file_hash': file_hash,
        'unique_id': unique_id,
        'file_size': len(content),
        'upload_time': datetime.utcnow()
    }
    files_col.insert_one(doc)

    flash('✅ File uploaded successfully!', 'success')
    return redirect('/dashboard')



# --- DOWNLOAD ---
@app.route('/download', methods=['POST'])
def download():
    if 'user' not in session:
        return redirect('/login')

    file_id = request.form['file_id']
    file_doc = files_col.find_one({'unique_id': file_id, 'owner': session['user']})
    if file_doc:
        filepath = os.path.join(UPLOAD_FOLDER, file_id)
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                encrypted = f.read()

            try:
                decrypted = fernet.decrypt(encrypted)
            except:
                return render_template('message.html', message='Decryption failed. Wrong key or corrupted file.')

            return send_file(
                BytesIO(decrypted),
                download_name=file_doc['filename'],
                as_attachment=True
            )

    return render_template('message.html', message='File not found.')

# --- DELETE ---
@app.route('/delete/<file_id>', methods=['POST'])
def delete(file_id):
    if 'user' not in session:
        return redirect('/login')
    file_doc = files_col.find_one({'unique_id': file_id, 'owner': session['user']})
    if file_doc:
        filepath = os.path.join(UPLOAD_FOLDER, file_id)
        if os.path.exists(filepath):
            os.remove(filepath)
        files_col.delete_one({'unique_id': file_id})
        return render_template('message.html', message='File deleted successfully.')
    return render_template('message.html', message='File not found.')

# === FILE PREVIEW ===
@app.route('/preview/<file_id>')
def preview(file_id):
    if 'user' not in session:
        return redirect('/login')

    file_doc = files_col.find_one({'unique_id': file_id, 'owner': session['user']})
    if not file_doc:
        return "File not found or you don't have permission", 404

    filepath = os.path.join(UPLOAD_FOLDER, file_id)
    if not os.path.exists(filepath):
        return "File not found on server", 404

    with open(filepath, 'rb') as f:
        encrypted = f.read()
    decrypted = fernet.decrypt(encrypted)

    ext = file_doc['filename'].lower()
    if ext.endswith('.png'):
        mimetype = 'image/png'
    elif ext.endswith('.jpg') or ext.endswith('.jpeg'):
        mimetype = 'image/jpeg'
    elif ext.endswith('.gif'):
        mimetype = 'image/gif'
    elif ext.endswith('.bmp'):
        mimetype = 'image/bmp'
    else:
        return "Preview not supported for this file type", 400

    return send_file(BytesIO(decrypted), mimetype=mimetype)

@app.route('/rename/<unique_id>', methods=['POST'])
def rename_file(unique_id):
    if 'user' not in session:
        return redirect('/login')

    new_name_raw = request.form.get('new_filename', '').strip()
    if not new_name_raw:
        flash('⚠️ New filename cannot be empty!', 'error')
        return redirect('/dashboard')

    file_doc = files_col.find_one({'unique_id': unique_id, 'owner': session['user']})
    if not file_doc:
        flash('⚠️ File not found or not allowed!', 'error')
        return redirect('/dashboard')

    current_ext = os.path.splitext(file_doc.get('filename', ''))[1].lower()
    new_filename = secure_filename(new_name_raw).lower() + current_ext

    if new_filename == file_doc.get('filename'):
        flash('⚠️ New name is same as current name.', 'info')
        return redirect('/dashboard')

    exists = files_col.find_one({
        'owner': session['user'],
        'filename': new_filename
    })
    if exists:
        flash('⚠️ A file with this name already exists!', 'error')
        return redirect('/dashboard')

    # Stored filename should already exist (unique_id + ext)
    stored_filename = file_doc.get('stored_filename')
    if not stored_filename:
        stored_filename = f"{unique_id}{current_ext}"
        possible_path = os.path.join(UPLOAD_FOLDER, stored_filename)
        if os.path.exists(possible_path):
            files_col.update_one(
                {'unique_id': unique_id, 'owner': session['user']},
                {'$set': {'stored_filename': stored_filename}}
            )
        else:
            flash('⚠️ Original file is missing on the server.', 'error')
            return redirect('/dashboard')

    # ✅ Only update DB, keep physical file name same
    files_col.update_one(
        {'unique_id': unique_id, 'owner': session['user']},
        {'$set': {'filename': new_filename}}
    )

    flash('✅ File renamed successfully!', 'success')
    return redirect('/dashboard')


# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')

# --- RUN APP ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
