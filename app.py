from flask import Flask, redirect, request, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import base64
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # For local dev; sessions not used in Vercel

# === GLOBAL STORAGE FOR TESTING ONLY ===
saved_creds = {}

# === Load Google credentials from ENV ===
CLIENT_SECRETS_FILE = "client_secrets_temp.json"
if not os.path.exists(CLIENT_SECRETS_FILE):
    with open(CLIENT_SECRETS_FILE, "w") as f:
        f.write(os.environ['GOOGLE_CREDENTIALS'])

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']

# ✅ Make sure this is your actual Vercel app URL
REDIRECT_URI = 'https://gmail-gpt-phi.vercel.app/oauth2callback'


@app.route('/')
def index():
    return 'GPT Gmail API is running!'


@app.route('/authorize')
def authorize():
    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = REDIRECT_URI
        auth_url, _ = flow.authorization_url(prompt='consent')
        return redirect(auth_url)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/oauth2callback')
def oauth2callback():
    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = REDIRECT_URI
        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials
        global saved_creds
        saved_creds = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }

        return redirect('/emails/latest')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emails/latest')
def get_latest_emails():
    try:
        if not saved_creds:
            return redirect('/authorize')

        creds = Credentials(**saved_creds)
        service = build('gmail', 'v1', credentials=creds)
        result = service.users().messages().list(userId='me', maxResults=5).execute()
        messages = result.get('messages', [])

        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
            snippet = msg_data.get('snippet')
            emails.append(snippet)

        return jsonify(emails)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/emails/send', methods=['POST'])
def send_email():
    try:
        if not saved_creds:
            return redirect('/authorize')

        data = request.json
        to = data['to']
        subject = data['subject']
        body = data['body']

        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        creds = Credentials(**saved_creds)
        service = build('gmail', 'v1', credentials=creds)
        service.users().messages().send(userId='me', body={'raw': raw}).execute()

        return jsonify({'status': 'Email sent!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
