from main import get_latest_email_body_text
import json
import re
import requests
from ollama import Client
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

MODEL = "llama3.2"
ALLOWED = {"INTENT_SCHEDULE_MEETING", "REQUEST_SCHEDULED_MEETING", "OTHER"}

LOCAL_TZ = datetime.now().astimezone().tzinfo

def _extract_json(text: str) -> dict:
    """
    Ollama models sometimes add extra text.
    This pulls out the first JSON object if needed.
    """
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("Model did not return JSON.")
    return json.loads(m.group(0))

def classify_with_ollama(email_body: str) -> dict:
    SYSTEM_PROMPT = """You are an email intent classifier.
    Choose exactly ONE label:
    - INTENT_SCHEDULE_MEETING: the sender gives an exact time for a meeting, It is set into place already the meeting. There is clear indication of date and time of the meeting for it to be scheduled. 
    - REQUEST_SCHEDULED_MEETING: the sender asks you to schedule/confirm/reschedule an already-discussed meeting, or logistical coordination (calendar invite, Zoom link, time change).
    - OTHER: everything else.

    Output ONLY valid JSON in this exact schema:
    {
    "label": "INTENT_SCHEDULE_MEETING" | "REQUEST_SCHEDULED_MEETING" | "OTHER",
    "confidence": number between 0 and 1,
    "rationale": "1-2 short sentences"
    }
    No extra keys. No markdown. No surrounding text.
    """
    client = Client()
    payload = client.chat(
        model=MODEL,
        messages= [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": email_body[:8000]}, #can change so that it takes more than 8000 of the first characters
        ],
        options= {
            "temperature": 0
        }
    )
    return payload["message"]["content"]

def extract_datetime_with_ollama(email_text: str, now: datetime | None = None) -> dict:
    """
    Returns ONLY fields needed to schedule a Google Calendar event:
      - start_iso (RFC3339/ISO8601 with offset) or ""
      - end_iso   (RFC3339/ISO8601 with offset) or ""
      - timezone  (IANA name if possible, otherwise offset like -0800)
      - needs_clarification (bool)
      - clarification_question (string)
    """
    if now is None:
        now = datetime.now().astimezone()  # local timezone-aware

    reference = now.isoformat()            # includes offset, e.g. 2026-01-12T18:03:00-08:00
    tz_offset = now.strftime("%z")         # e.g. -0800

    system_prompt = f"""You extract meeting start/end datetime from an email.

Reference datetime (user local time): {reference}
User timezone offset: {tz_offset}

Rules:
- Resolve relative dates like "tomorrow", "next Monday" using the reference datetime.
- If the email provides an exact meeting time, output start_iso and end_iso as RFC3339/ISO8601 with offset.
- If duration is not stated, assume 30 minutes.
- If the email only provides a window (e.g. "2-4pm") or is missing a date or time, do NOT guess.
  Set start_iso="" and end_iso="" and needs_clarification=true, with a short clarification_question.

Output ONLY valid JSON with EXACTLY these keys:
{{
  "start_iso": string,
  "end_iso": string,
  "timezone": string,
  "needs_clarification": boolean,
  "clarification_question": string
}}
No extra text.
"""

    client = Client()
    resp = client.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": email_text[:12000]},
        ],
        options={"temperature": 0},
    )

    data = _extract_json(resp["message"]["content"])

    # Ensure required keys exist + keep timezone as a string
    data.setdefault("timezone", tz_offset)
    data.setdefault("start_iso", "")
    data.setdefault("end_iso", "")
    data.setdefault("needs_clarification", False)
    data.setdefault("clarification_question", "")

    return data


def recieved_Intent(email_text: str):
    data2 = extract_datetime_with_ollama(email_text)
    print("Extracted datetime info:")
    print(data2["start_iso"])

if __name__ == "__main__":
    body = get_latest_email_body_text()
    result = classify_with_ollama(body["body"]["content"])
    result2 = _extract_json(result)
    print(LOCAL_TZ)
    print(result)
    print(result2["label"])

    if result2["label"] == "INTENT_SCHEDULE_MEETING":
        recieved_Intent(body["body"]["content"])

    