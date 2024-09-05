from flask import Flask, request, send_file, redirect, render_template, flash, url_for
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
import speech_recognition as sr
from pydub import AudioSegment
import tempfile

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSED_FOLDER'] = 'processed'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Define User model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    files = db.relationship('File', backref='owner', lazy=True)

class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(150), nullable=False)
    processed_filename = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def extract_audio(video_path, audio_path):
    video = VideoFileClip(video_path)
    audio = video.audio
    audio.write_audiofile(audio_path)

def audio_to_text(audio_path):
    recognizer = sr.Recognizer()
    audio = AudioSegment.from_wav(audio_path)
    chunk_length_ms = 5000  
    overlap_ms = 1000  
    chunks = []

    for i in range(0, len(audio), chunk_length_ms - overlap_ms):
        chunk = audio[i:i + chunk_length_ms]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_chunk_file:
            chunk.export(temp_chunk_file.name, format="wav")

        with sr.AudioFile(temp_chunk_file.name) as source:
            audio_data = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio_data)
                chunks.append({
                    'start': i / 1000.0,
                    'end': (i + chunk_length_ms) / 1000.0,
                    'text': text
                })
            except sr.UnknownValueError:
                continue
            except sr.RequestError:
                continue
        os.remove(temp_chunk_file.name)

    return chunks

def add_subtitles(video_path, subtitles, output_path):
    video = VideoFileClip(video_path)
    subtitle_clips = []

    for subtitle in subtitles:
        subtitle_clip = TextClip(subtitle['text'], fontsize=24, color='white', bg_color='black', size=(video.w, 100))
        subtitle_clip = subtitle_clip.set_duration(subtitle['end'] - subtitle['start'])
        subtitle_clip = subtitle_clip.set_start(subtitle['start']).set_position(('center', 'bottom'))
        subtitle_clips.append(subtitle_clip)

    video_with_subtitles = CompositeVideoClip([video] + subtitle_clips)
    video_with_subtitles.write_videofile(output_path, codec='libx264', audio_codec='aac')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'video' not in request.files:
        return redirect(request.url)
    file = request.files['video']
    if file.filename == '':
        return redirect(request.url)
    
    filename = secure_filename(file.filename)
    video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    processed_path = os.path.join(app.config['PROCESSED_FOLDER'], 'processed_' + filename)

    file.save(video_path)

    audio_path = os.path.join(app.config['UPLOAD_FOLDER'], 'audio.wav')
    extract_audio(video_path, audio_path)
    subtitles = audio_to_text(audio_path)
    add_subtitles(video_path, subtitles, processed_path)

    # Save the file entry for the logged-in user
    if current_user.is_authenticated:
        new_file = File(filename=filename, processed_filename='processed_' + filename, user_id=current_user.id)
        db.session.add(new_file)
        db.session.commit()

    return render_template('result.html', processed_filename='processed_' + filename)


@app.route('/processed/<filename>')
def processed_file(filename):
    return send_file(os.path.join(app.config['PROCESSED_FOLDER'], filename), as_attachment=False)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='sha256')
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('feed'))
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('feed'))
        flash('Login failed. Check your credentials', 'danger')
    return render_template('login.html')



@app.route('/feed')
@login_required
def feed():
    user_files = File.query.filter_by(user_id=current_user.id).all()
    return render_template('feed.html', files=user_files)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)
    app.run(debug=True)
