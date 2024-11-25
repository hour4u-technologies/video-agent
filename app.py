from flask import Flask, request, render_template, jsonify, session
import os
import time
import google.generativeai as genai
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import NoCredentialsError
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key

# Configure Google Gemini AI
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION")

# Load AWS credentials from environment variables
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Create an S3 client using boto3
s3_client = boto3.client(
    's3',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_s3(file_bytes, filename, bucket_name):
    """Uploads the given file bytes to S3 and returns the public URL."""
    try:
        s3_client.upload_fileobj(
            file_bytes,
            bucket_name,
            filename,
            ExtraArgs={'ContentType': 'video/mp4', 'ACL': 'public-read'}
        )
        file_url = f'https://{bucket_name}.s3.{AWS_REGION}.amazonaws.com/{filename}'
        return file_url
    except Exception as e:
        raise Exception(f"Error uploading to S3: {str(e)}")

def upload_to_gemini(file_bytes, mime_type="video/mp4"):
    """Uploads the given file bytes to Gemini."""
    try:
        gemini_file = genai.upload_file(file_bytes, mime_type=mime_type)
        return gemini_file
    except Exception as e:
        raise Exception(f"Error uploading to Gemini: {str(e)}")

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
        "top_k": 40,
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
        try:
            filename = secure_filename(file.filename)

            # Read file into memory as bytes
            file_bytes = BytesIO(file.read())

            # Step 1: Upload to S3
            s3_file_bytes = BytesIO(file_bytes.getvalue())  # Create a separate stream for S3
            video_url = upload_to_s3(s3_file_bytes, filename, S3_BUCKET_NAME)

            # Step 2: Upload to Gemini
            gemini_file_bytes = BytesIO(file_bytes.getvalue())  # Create a separate stream for Gemini
            gemini_file = upload_to_gemini(gemini_file_bytes, mime_type="video/mp4")
            wait_for_files_active([gemini_file])

            # Store the file URI and URL in session
            session['video_file_uri'] = gemini_file.uri
            session['video_file_name'] = gemini_file.name
            session['video_file_url'] = video_url  # Save the public URL for the preview

            return jsonify({'message': 'Video processed successfully', 'video_url': video_url}), 200
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
            history=[{
                "role": "user",
                "parts": [file],
            }]
        )

        # Send the question and get response
        response = chat.send_message(question)
        return jsonify({'answer': response.text}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)