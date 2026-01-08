import base64
from email.utils import parsedate_to_datetime
import json

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CLIENT_FILE = "client.json"

def b64url_decode(data: str) -> str:
    """
    Gmail returns email bodies as base64-url-safe encoded strings.
    This decodes them into normal text.
    """
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")

def headers_to_dict(headers):
    """
    Gmail returns headers as a list of {name, value} pairs.
    This turns it into a normal dict like {"from": "...", "subject": "..."}.
    """
    return {h["name"].lower(): h["value"] for h in (headers or [])}

def extract_body_text(payload) -> dict:
    """
    Gmail message bodies can be multipart (nested parts).
    We walk the structure and select the best body:
      1) first text/plain found
      2) else first text/html found
    Returns {"mimeType": "...", "content": "..."}.
    """
    best_plain = None
    best_html = None

    def walk(part):
        nonlocal best_plain, best_html

        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")  # base64url text for this part, if present

        if data:
            text = b64url_decode(data)
            if mime == "text/plain" and best_plain is None:
                best_plain = text
            elif mime == "text/html" and best_html is None:
                best_html = text

        # If this part is multipart, recurse into children
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload or {})

    if best_plain is not None:
        return {"mimeType": "text/plain", "content": best_plain}
    if best_html is not None:
        return {"mimeType": "text/html", "content": best_html}
    return {"mimeType": None, "content": ""}

def build_gmail_service():
    """
    Why this exists:
    - Gmail API requires an OAuth access token.
    - This function runs the interactive browser flow and returns a Gmail client.

    What happens:
    - Reads CLIENT_FILE (client_id, redirect URI, etc.)
    - Opens browser for you to log in and approve SCOPES
    - Returns credentials (access token) in memory
    - Builds a Gmail API client object you can call .users().messages() on
    """
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(port=0)  # port=0 picks a free local port
    return build("gmail", "v1", credentials=creds)

def get_most_recent_message_id(service, inbox_only=True) -> str | None:
    """
    Gmail API pattern:
    - users.messages.list gives you message IDs (not bodies)
    - maxResults=1 means "only the newest one"
    - labelIds=["INBOX"] restricts to Inbox (optional)

    Returns the message id string, or None if no messages.
    """
    params = {"userId": "me", "maxResults": 1}
    if inbox_only:
        params["labelIds"] = ["INBOX"]

    resp = service.users().messages().list(**params).execute()
    msgs = resp.get("messages", [])
    return msgs[0]["id"] if msgs else None

def fetch_message_structured(service, message_id: str) -> dict:
    """
    To get body text, we must fetch the full message:
    - users.messages.get(format="full") returns headers + MIME payload parts.
    - We parse headers and decode the best text body from parts.

    Returns a clean dict suitable for logging / downstream processing.
    """
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    payload = msg.get("payload", {}) or {}
    hdrs = headers_to_dict(payload.get("headers", []))

    # Email Date header can be inconsistent; we try to normalize to ISO.
    raw_date = hdrs.get("date", "")
    try:
        date_iso = parsedate_to_datetime(raw_date).isoformat() if raw_date else ""
    except Exception:
        date_iso = ""

    body = extract_body_text(payload)

    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds", []),
        "internalDate_ms": msg.get("internalDate"),  # Gmail's internal timestamp
        "headers": {
            "from": hdrs.get("from", ""),
            "to": hdrs.get("to", ""),
            "subject": hdrs.get("subject", ""),
            "date_raw": raw_date,
            "date_iso": date_iso,
        },
        "snippet": msg.get("snippet", ""),
        "body": body,  # {"mimeType": "text/plain"|"text/html", "content": "..."}
    }


if __name__ == "__main__":
    # 1) Authenticate + create Gmail API client
    service = build_gmail_service()

    # 2) Get newest message ID (Inbox)
    msg_id = get_most_recent_message_id(service, inbox_only=True)
    if not msg_id:
        print(json.dumps({"error": "No messages found in Inbox."}, indent=2))
        raise SystemExit(0)

    # 3) Fetch message and decode body
    structured = fetch_message_structured(service, msg_id)

    # Print a structured JSON object
    print(structured["body"]["content"])



