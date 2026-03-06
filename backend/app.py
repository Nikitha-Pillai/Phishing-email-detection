from flask_cors import CORS
from flask import Flask, redirect, session, request, jsonify
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import os
import json
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from bs4 import BeautifulSoup
import torch
import torch.nn.functional as F
from transformers import BertTokenizer, BertForSequenceClassification

# ==========================================================
# CONFIG
# ==========================================================

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly"
]
PROJECT_ID = "email-detection-42c8f"
PUBSUB_TOPIC = f"projects/{PROJECT_ID}/topics/gmail-topic"

app = Flask(__name__)
app.secret_key = "super_secret_key_123"
CORS(app)

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# ==========================================================
# FIREBASE INIT
# ==========================================================

cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# LOAD BERT MODEL
# ==========================================================

MODEL_PATH = "bert_model"

tokenizer = BertTokenizer.from_pretrained(MODEL_PATH)
model = BertForSequenceClassification.from_pretrained(MODEL_PATH)
model.eval()

# ==========================================================
# HELPER FUNCTIONS
# ==========================================================

def detect_email(text):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs = F.softmax(outputs.logits, dim=1)
    confidence, predicted = torch.max(probs, dim=1)

    label = "Phishing" if predicted.item() == 1 else "Legitimate"
    return label, confidence.item()


def clean_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def get_gmail_service():
    doc = db.collection("gmail_tokens").document("user").get()

    if not doc.exists:
        return None

    creds_dict = doc.to_dict()

    creds = Credentials(
        token=creds_dict["token"],
        refresh_token=creds_dict["refresh_token"],
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=creds_dict["scopes"]
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        db.collection("gmail_tokens").document("user").update({
            "token": creds.token
        })

    return build('gmail', 'v1', credentials=creds)


def process_latest_email():
    service = get_gmail_service()
    if not service:
        print("No Gmail token")
        return

    results = service.users().messages().list(
        userId='me',
        maxResults=1
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return

    msg_id = messages[0]['id']

    # Prevent duplicate processing
    if db.collection("emails").document(msg_id).get().exists:
        print("Already processed")
        return

    msg = service.users().messages().get(
        userId='me',
        id=msg_id,
        format='full'
    ).execute()

    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    subject = ""
    for header in headers:
        if header["name"] == "Subject":
            subject = header["value"]
            break

    body = msg.get("snippet", "")
    cleaned_body = clean_html(body)

    label, confidence = detect_email(subject + " " + cleaned_body)

    db.collection("emails").document(msg_id).set({
        "email_id": msg_id,
        "subject": subject,
        "content": cleaned_body,
        "prediction": label,
        "confidence": confidence
    })

    if confidence < 0.95:
        db.collection("low_confidence").document(msg_id).set({
        "email_id": msg_id,
        "subject": subject,
        "content": cleaned_body,
        "prediction": label,
        "confidence": confidence,
        "feedback_given": False
    })

    print("Email processed:", subject)


# ==========================================================
# ROUTES
# ==========================================================

@app.route("/")
def home():
    return """
    <h2>AI Phishing Email Detector</h2>
    <a href="/login">Login Gmail</a><br><br>
    <a href="/watch">Start Gmail Watch</a>
    """


@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        redirect_uri=os.environ.get(
            "REDIRECT_URI",
            "http://localhost:8080/oauth2callback"
        )
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    session["state"] = state
    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        state=session["state"],
        redirect_uri=os.environ.get(
            "REDIRECT_URI",
            "http://localhost:8080/oauth2callback"
        )
    )

    flow.fetch_token(authorization_response=request.url)
    credentials_obj = flow.credentials

    db.collection("gmail_tokens").document("user").set({
    "token": credentials_obj.token,
    "refresh_token": credentials_obj.refresh_token,
    "token_uri": credentials_obj.token_uri,
    "client_id": credentials_obj.client_id,
    "client_secret": credentials_obj.client_secret,
    "scopes": credentials_obj.scopes
    })

    return "Gmail Connected Successfully!"


@app.route("/watch")
def start_watch():
    service = get_gmail_service()
    if not service:
        return "Login first"

    request_body = {
        'labelIds': ['INBOX'],
        'topicName': PUBSUB_TOPIC
    }

    response = service.users().watch(
        userId='me',
        body=request_body
    ).execute()

    return response


# ==========================================================
# PUBSUB WEBHOOK (REALTIME)
# ==========================================================

@app.route("/gmail/webhook", methods=["POST"])
def gmail_webhook():

    envelope = request.get_json()

    if not envelope or "message" not in envelope:
        return ("Bad Request", 400)

    pubsub_message = envelope["message"]

    if "data" in pubsub_message:
        decoded_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        print("Push Data:", decoded_data)

    print("Gmail Push Received")

    process_latest_email()

    return ("", 200)


# ==========================================================
# DASHBOARD API
# ==========================================================

@app.route("/api/emails")
def get_emails():
    docs = db.collection("emails").stream()

    email_list = []
    for doc in docs:
        email_list.append(doc.to_dict())

    return jsonify(email_list)

@app.route("/api/low-confidence")
def get_low_confidence():

    docs = db.collection("low_confidence")\
             .where("feedback_given", "==", False)\
             .stream()

    emails = []

    for doc in docs:
        emails.append(doc.to_dict())

    return jsonify(emails)

@app.route("/api/submit-feedback", methods=["POST"])
def submit_feedback():

    data = request.json

    email_id = data["email_id"]
    user_label = data["user_label"]

    doc = db.collection("low_confidence").document(email_id).get()

    if not doc.exists:
        return jsonify({"error": "Email not found"}), 404

    email_data = doc.to_dict()

    # Save feedback
    db.collection("user_feedback").add({
        "email_id": email_id,
        "subject": email_data["subject"],
        "content": email_data["content"],
        "user_label": user_label,
        "model_prediction": email_data["prediction"],
        "confidence": email_data["confidence"]
    })

    # Mark feedback as given
    db.collection("low_confidence").document(email_id).update({
        "feedback_given": True
    })

    return jsonify({"message": "Feedback stored"})


# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))