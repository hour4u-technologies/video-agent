from flask import Flask, request, render_template, jsonify, session
import os
import time
import google.generativeai as genai
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key

# Configure Google Gemini AI
genai.configure(api_key="AIzaSyDRYel9bkqYXQjCqj7WVJt-bEg331kOyEw")

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_gemini(path, mime_type=None):
    """Uploads the given file to Gemini."""
    file = genai.upload_file(path, mime_type=mime_type)
    return file

def wait_for_files_active(files):
    """Waits for the given files to be active."""
    for name in (file.name for file in files):
        file = genai.get_file(name)
        while file.state.name == "PROCESSING":
            time.sleep(2)
            file = genai.get_file(name)
        if file.state.name != "ACTIVE":
            raise Exception(f"File {file.name} failed to process")
    return True

def initialize_gemini_model():
    """Initialize and return the Gemini model."""
    generation_config = {
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 64,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
    }
    
    return genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config=generation_config
    )

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Upload to Gemini
            gemini_file = upload_to_gemini(filepath, mime_type="video/mp4")
            wait_for_files_active([gemini_file])
            
            # Store the file URI in session
            session['video_file_uri'] = gemini_file.uri
            session['video_file_name'] = gemini_file.name
            
            return jsonify({'message': 'Video processed successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/ask', methods=['POST'])
def ask_question():
    if 'video_file_uri' not in session or 'video_file_name' not in session:
        return jsonify({'error': 'No video has been processed yet'}), 400
    
    question = request.json.get('question')
    if not question:
        return jsonify({'error': 'No question provided'}), 400
    
    try:
        # Get the file from session data
        file = genai.get_file(session['video_file_name'])
        
        # Initialize new chat session for each question
        model = initialize_gemini_model()
        chat = model.start_chat(
            history=[
                {
                    "role": "user",
                    "parts": [file],
                },
            ]
        )
        
        # Send the question and get response
        response = chat.send_message(question)
        return jsonify({'answer': response.text}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)