import firebase_admin
from firebase_admin import credentials, firestore
from transformers import AutoTokenizer, AutoModelForCausalLM
import time

# Initialize Firebase
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

print("Loading TinyLlama model...")

MODEL_NAME = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)

print("TinyLlama loaded successfully")


# Generate ONE email
def generate_single_email(content, label):

    if label.lower() == "phishing":
        prompt = f"""
Write ONE realistic phishing email similar to the email below.
The email must be complete and convincing.

Email:
{content}

Generated email:
"""
    else:
        prompt = f"""
Write ONE professional legitimate email similar to the email below.
The email must be complete.

Email:
{content}

Generated email:
"""

    inputs = tokenizer(prompt, return_tensors="pt")

    outputs = model.generate(
        **inputs,
        max_new_tokens=200,
        temperature=0.9,
        do_sample=True,
        top_p=0.95
    )

    text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    generated = text.split("Generated email:")[-1].strip()

    return generated


# Generate 5 unique emails
def generate_5_unique_emails(content, label):

    emails = set()
    attempts = 0

    while len(emails) < 5 and attempts < 20:

        email = generate_single_email(content, label)

        if len(email) > 50:
            emails.add(email.strip())

        attempts += 1

    return list(emails)


def process_generation():

    docs = db.collection("user_feedback").stream()

    for doc in docs:

        data = doc.to_dict()

        status = data.get("generation_status", "pending")

        if status == "completed":
            continue

        email_id = data["email_id"]
        subject = data["subject"]
        content = data["content"]
        label = data["user_label"]

        print("Generating emails for:", email_id)

        # Check if emails already generated
        existing = db.collection("generated_emails") \
            .where("original_email_id", "==", email_id) \
            .stream()

        if len(list(existing)) > 0:
            print("Emails already generated for:", email_id)
            continue

        generated_emails = generate_5_unique_emails(content, label)

        for email in generated_emails:

            db.collection("generated_emails").add({
                "original_email_id": email_id,
                "subject": subject,
                "content": email,
                "label": label,
                "generated_by": "tinyllama",
                "training_status": "pending"
            })

        db.collection("user_feedback").document(doc.id).update({
            "generation_status": "completed"
        })

        print("Generation completed for:", email_id)


def background_worker():

    while True:

        try:
            process_generation()
        except Exception as e:
            print("Service2 error:", e)

        time.sleep(600)  # check every 10 minutes