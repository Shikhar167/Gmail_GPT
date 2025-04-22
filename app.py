from flask import Flask, redirect, request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import json
import base64
import traceback
from email.mime.text import MIMEText
import html

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# === Temporary in-memory credential store (1 user for testing) ===
saved_creds = {}

# === Load Gmail API credentials from env ===
if 'GOOGLE_CREDENTIALS' not in os.environ:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

GOOGLE_CREDS_DICT = json.loads(os.environ['GOOGLE_CREDENTIALS'])
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = 'https://gmail-gpt-phi.vercel.app/oauth2callback'


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
        return _error_response(e)


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
        return _error_response(e)


@app.route('/emails/latest')
def get_latest_emails():
    try:
        if not saved_creds:
            return redirect('/authorize')

        creds = Credentials(**saved_creds)
        service = build('gmail', 'v1', credentials=creds)

        result = service.users().messages().list(userId='me', maxResults=3).execute()
        messages = result.get('messages', [])

        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()

            headers = msg_data.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender_raw = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
            sender = html.unescape(sender_raw)

            # Normalize sender format to: Name - email@domain.com
            if '<' in sender and '>' in sender:
                name, email = sender.split('<', 1)
                email = email.replace('>', '').strip()
                name = name.strip()
                sender = f"{name} - {email}"
            sender = sender[:100]  # Truncate just in case

            emails.append({
                'id': msg['id'],
                'from': sender,
                'subject': subject[:100]
            })

        return _json_response(emails)
    except Exception as e:
        print("🔥 Exception in /emails/latest:", traceback.format_exc())
        return _error_response(e)


@app.route('/emails/detail')
def get_email_detail():
    try:
        if not saved_creds:
            return redirect('/authorize')

        email_id = request.args.get('id')
        if not email_id:
            return _error_response("Missing email ID", status=400)

        creds = Credentials(**saved_creds)
        service = build('gmail', 'v1', credentials=creds)

        msg_data = service.users().messages().get(
            userId='me',
            id=email_id,
            format='full'
        ).execute()

        headers = msg_data.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
        sender_raw = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
        sender = html.unescape(sender_raw)

        if '<' in sender and '>' in sender:
            name, email = sender.split('<', 1)
            email = email.replace('>', '').strip()
            name = name.strip()
            sender = f"{name} - {email}"

        # Extract plain text body
        body = ''
        payload = msg_data.get('payload', {})
        parts = payload.get('parts', [])

        for part in parts:
            if part.get('mimeType') == 'text/plain' and part['body'].get('data'):
                body = base64.urlsafe_b64decode(part['body']['data'] + '==').decode('utf-8')
                break

        if not body and payload.get('body', {}).get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data'] + '==').decode('utf-8')

        return _json_response({
            'from': sender[:100],
            'subject': subject[:100],
            'body': body.strip().replace('\r\n', '\n')[:500]
        })
    except Exception as e:
        print("🔥 Exception in /emails/detail:", traceback.format_exc())
        return _error_response(e)


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

        return _json_response({'status': 'Email sent!'})
    except Exception as e:
        print("🔥 Exception in /emails/send:", traceback.format_exc())
        return _error_response(e)


# === Helper for compact JSON ===
def _json_response(data, status=200):
    return app.response_class(
        response=json.dumps(data, separators=(',', ':')),
        status=status,
        mimetype='application/json'
    )


# === Helper for compact error response ===
def _error_response(error, status=500):
    return _json_response({'error': str(error)}, status=status)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
