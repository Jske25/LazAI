from main import get_latest_email_body_text
import json
import re
import requests
from ollama import Client

MODEL = "llama3.2"
ALLOWED = {"INTENT_SCHEDULE_MEETING", "REQUEST_SCHEDULED_MEETING", "OTHER"}

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
    - INTENT_SCHEDULE_MEETING: the sender gives a time for a meeting, It is set into place already the meeting. There is clear indication of date and time of the meeting for it to be scheduled. 
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


def main():
    print('test')

if __name__ == "__main__":
    body = get_latest_email_body_text()
    result = classify_with_ollama(body)
    print(result)

    