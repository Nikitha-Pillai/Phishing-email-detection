from flask import Flask, redirect, session, request, jsonify
from flask_cors import CORS
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import os
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
# LOAD MODEL (LAZY LOADING FIX)
# ==========================================================

MODEL_PATH = "bert_model"

tokenizer = None
model = None

def load_model():
    global tokenizer, model

    if tokenizer is None or model is None:
        print("Loading BERT model...")
        tokenizer = BertTokenizer.from_pretrained(MODEL_PATH)
        model = BertForSequenceClassification.from_pretrained(MODEL_PATH)
        model.eval()
        print("Model loaded")

# ==========================================================
# HELPER FUNCTIONS
# ==========================================================

def detect_email(text):

    load_model()

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

def get_email_body(payload):

    if "parts" in payload:
        for part in payload["parts"]:

            if part["mimeType"] == "text/plain":
                data = part["body"].get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8")

            if part["mimeType"] == "text/html":
                data = part["body"].get("data")
                if data:
                    html = base64.urlsafe_b64decode(data).decode("utf-8")
                    return clean_html(html)

    data = payload.get("body", {}).get("data")

    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8")

    return ""

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

    return build("gmail", "v1", credentials=creds)

# ==========================================================
# EMAIL PROCESSING
# ==========================================================

def process_latest_email():

    try:

        service = get_gmail_service()

        if not service:
            print("No Gmail token")
            return

        results = service.users().messages().list(
            userId="me",
            labelIds=["INBOX"],
            maxResults=5
        ).execute()

        messages = results.get("messages", [])

        if not messages:
            return

        for message in messages:

            msg_id = message["id"]

            if db.collection("emails").document(msg_id).get().exists:
                continue

            msg = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full"
            ).execute()

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            subject = ""

            for header in headers:
                if header["name"] == "Subject":
                    subject = header["value"]
                    break

            body = get_email_body(payload)

            label, confidence = detect_email(subject + " " + body)

            db.collection("emails").document(msg_id).set({
                "email_id": msg_id,
                "subject": subject,
                "content": body,
                "prediction": label,
                "confidence": confidence
            })

            if confidence < 0.95:

                db.collection("low_confidence").document(msg_id).set({
                    "email_id": msg_id,
                    "subject": subject,
                    "content": body,
                    "prediction": label,
                    "confidence": confidence,
                    "feedback_given": False
                })

            print("Email processed:", subject)

            break

    except Exception as e:
        print("Email processing error:", e)

# ==========================================================
# ROUTES
# ==========================================================

@app.route("/")
def home():
    return "AI Phishing Email Detector Running"

@app.route("/health")
def health():
    return "OK"

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

# ==========================================================
# PUBSUB WEBHOOK
# ==========================================================

@app.route("/gmail/webhook", methods=["POST"])
def gmail_webhook():

    envelope = request.get_json()

    if not envelope or "message" not in envelope:
        return ("Bad Request", 400)

    print("Gmail push received")

    process_latest_email()

    return ("", 200)

# ==========================================================
# API ROUTES
# ==========================================================

@app.route("/api/emails")
def get_emails():

    docs = db.collection("emails").stream()

    emails = [doc.to_dict() for doc in docs]

    return jsonify(emails)

@app.route("/api/low-confidence")
def get_low_confidence():

    docs = db.collection("low_confidence").stream()

    emails = []

    for doc in docs:
        data = doc.to_dict()
        if data.get("feedback_given") == False:
            emails.append(data)

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

    db.collection("user_feedback").add({
        "email_id": email_id,
        "subject": email_data["subject"],
        "content": email_data["content"],
        "user_label": user_label,
        "model_prediction": email_data["prediction"],
        "confidence": email_data["confidence"],
        "generation_status":"pending"
    })

    db.collection("low_confidence").document(email_id).update({
        "feedback_given": True
    })

    return jsonify({"message": "Feedback stored"})

# ==========================================================
# RUN
# ==========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))