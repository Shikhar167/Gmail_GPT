from flask import Flask, redirect, request, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import json
import base64
import traceback
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # For local dev

# === Temporary in-memory store for auth credentials ===
saved_creds = {}

# === Load Google credentials from ENV ===
if 'GOOGLE_CREDENTIALS' not in os.environ:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

GOOGLE_CREDS_DICT = json.loads(os.environ['GOOGLE_CREDENTIALS'])
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = 'https://gmail-gpt-phi.vercel.app/oauth2callback'  # ✅ Replace if your domain changes


@app.route('/')
def index():
    return 'GPT Gmail API is running!'


@app.route('/authorize')
def authorize():
    try:
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES)
        flow.redirect_uri = REDIRECT_URI
        auth_url, _ = flow.authorization_url(prompt='consent')
        return redirect(auth_url)
    except Exception as e:
        print("🔥 Exception in /authorize:", traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/oauth2callback')
def oauth2callback():
    try:
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES)
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
        print("🔥 Exception in /oauth2callback:", traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/emails/latest')
def get_latest_emails():
    try:
        if not saved_creds:
            return redirect('/authorize')

        creds = Credentials(**saved_creds)
        service = build('gmail', 'v1', credentials=creds)

        result = service.users().messages().list(userId='me', maxResults=1).execute()
        messages = result.get('messages', [])

        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])

            # Extract subject
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')

            # Extract plain text body (limit length)
            body = ''
            parts = payload.get('parts', [])
            for part in parts:
                if part.get('mimeType') == 'text/plain':
                    body_data = part['body'].get('data', '')
                    body = base64.urlsafe_b64decode(body_data + '==').decode('utf-8')
                    break

            if not body and 'body' in payload and payload['body'].get('data'):
                body_data = payload['body']['data']
                body = base64.urlsafe_b64decode(body_data + '==').decode('utf-8')

            emails.append({
                'subject': subject,
                'body': body[:1000]  # truncate to avoid GPT size limits
            })

        return jsonify(emails)
    except Exception as e:
        print("🔥 Exception in /emails/latest:", traceback.format_exc())
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
        print("🔥 Exception in /emails/send:", traceback.format_exc())
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
