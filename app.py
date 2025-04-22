from flask import Flask, redirect, request, session, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import pathlib

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this to something random

# OAuth flow setup
CLIENT_SECRETS_FILE = "client_secrets_temp.json"
if not os.path.exists(CLIENT_SECRETS_FILE):
    with open(CLIENT_SECRETS_FILE, "w") as f:
        f.write(os.environ['GOOGLE_CREDENTIALS'])
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = 'https://gmail-gpt-e4fs.onrender.com'


@app.route('/')
def index():
    return 'GPT Gmail API is running!'

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

    return redirect('/emails/latest')

@app.route('/emails/latest')
def get_latest_emails():
    creds = session.get('credentials')
    if not creds:
        return redirect('/authorize')

    service = build('gmail', 'v1', credentials=Credentials(**creds))
    result = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = result.get('messages', [])

    emails = []
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
        snippet = msg_data.get('snippet')
        emails.append(snippet)

    return jsonify(emails)

@app.route('/emails/send', methods=['POST'])
def send_email():
    creds = session.get('credentials')
    if not creds:
        return redirect('/authorize')

    data = request.json
    to = data['to']
    subject = data['subject']
    body = data['body']

    from email.mime.text import MIMEText
    import base64

    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    service = build('gmail', 'v1', credentials=Credentials(**creds))
    service.users().messages().send(userId='me', body={'raw': raw}).execute()

    return jsonify({'status': 'Email sent!'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
