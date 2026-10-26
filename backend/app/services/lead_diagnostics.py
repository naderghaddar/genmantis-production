"""Structured funnel events without contact names, email addresses or credentials."""
import json
import logging


logger = logging.getLogger("uvicorn.error.lead_funnel")


def emit(event: str, **fields):
    logger.info("lead_funnel %s", json.dumps({"event": event, **fields}, sort_keys=True))
