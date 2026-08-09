import json

import requests

from picker.config import DEFAULT_WEBHOOK_URL
from picker.logging_utils import log_event


def send_to_webhook(payload, webhook_url=DEFAULT_WEBHOOK_URL, timeout_seconds=60):
    job_id = payload.get("job_id")
    serialized_payload = json.dumps(payload, default=str, sort_keys=True)
    log_event(
        "webhook_started",
        job_id=job_id,
        webhook_url=webhook_url,
        timeout_seconds=timeout_seconds,
        item_count=len(payload.get("items", [])),
    )
    try:
        resp = requests.post(
            webhook_url,
            data=serialized_payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        log_event(
            "webhook_succeeded",
            job_id=job_id,
            status_code=resp.status_code,
            response_text=resp.text,
        )
        return {
            "ok": True,
            "job_id": job_id,
            "status_code": resp.status_code,
            "message": "Lists generated.",
            "response_text": resp.text,
        }
    except requests.RequestException as exc:
        response_text = None
        if exc.response is not None:
            try:
                response_text = exc.response.text
            except Exception:
                response_text = "<unavailable>"
        log_event(
            "webhook_failed",
            level="error",
            job_id=job_id,
            error=str(exc),
            webhook_url=webhook_url,
            payload=payload,
            payload_json=serialized_payload,
            response_status_code=getattr(exc.response, "status_code", None),
            response_text=response_text,
        )
        return {
            "ok": False,
            "job_id": job_id,
            "status_code": getattr(exc.response, "status_code", None),
            "message": "Something went wrong. The lists may have still generated, so check Drive before trying again.",
            "error": str(exc),
            "response_text": response_text,
        }
