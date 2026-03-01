from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
import json

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def create_flow():
    return Flow.from_client_secrets_file(
        'credentials.json',
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/oauth2callback'
    )

def get_gmail_service(creds_dict):
    creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
    return build('gmail', 'v1', credentials=creds)