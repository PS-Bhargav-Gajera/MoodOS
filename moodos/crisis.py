"""Crisis short-circuit — deterministic phrase check, no LLM, no writes.

On a match the app returns one warm support message in the existing chat
response shape (`mode: "chat"`), which static/app.js already renders via
renderChat. The crisis path never reaches resolve_location (no network, no
409), run_pipeline (no plan, no save_event/journal/mem0), the chat LLM leg,
or any logging of the message text.
"""

from __future__ import annotations

import re
from typing import Any

TELE_MANAS_HELP = (
    "If you are in immediate danger, call 112. "
    "In India, Tele-MANAS offers free, 24/7 mental-health support — "
    "call 14416 or 1-800-891-4416."
)

CRISIS_REPLY = (
    "I'm really sorry you're carrying this — you don't have to face it alone. "
    "Please reach out right now to someone you trust — a friend, family member, "
    "or anyone near you — and tell them how you're feeling. " + TELE_MANAS_HELP
)

# "end it" is only a crisis phrase with explicit intent: end it all / end my
# life / thinking about ending it / want to end it / going to end it. A plan
# step like "end it with a movie" must never match.
_CRISIS_PATTERNS = (
    r"kill\s*my(?:self|\s*self)\b",
    r"want(?:ed)?\s+to\s+die\b",
    r"end\s+it\s+all\b",
    r"end\s+my\s+life\b",
    r"(?:thinking|thought)\s+(?:about|of)\s+ending\s+it\b",
    r"(?:want|going)\s+to\s+end\s+it\b",
    r"self[\s-]?harm\b",
    r"(?:want|wanting|going)\s+to\s+(?:hurt|harm|cut|burn)\s+my(?:self|\s*self)\b",
    r"(?:don[’']?t|do\s+not)\s+want\s+to\s+"
    r"(?:be\s+here|be\s+alive|live|exist|go\s+on)(?:\s+anymore)?\b",
    r"no\s+(?:reason|point)\s+to\s+(?:live|go\s+on)\b",
    r"better\s+off\s+dead\b",
    r"take\s+my\s+(?:own\s+)?life\b",
)
_FLAGS = re.IGNORECASE


def is_crisis(message: str) -> bool:
    """True when the message carries a clear self-harm / suicide phrase.

    "sad", "tired" or "hopeless" alone never trigger this. The film title
    "Suicide Squad" is excluded; every other "suicide" mention triggers.
    """
    text = message or ""
    if re.search(r"suicide", text, _FLAGS) and not re.search(
        r"suicide\s+squad", text, _FLAGS
    ):
        return True
    return any(re.search(p, text, _FLAGS) for p in _CRISIS_PATTERNS)


def crisis_reply() -> dict[str, Any]:
    """Chat-shaped reply the existing frontend path already renders.

    No "location" key on purpose: app.py's post-processing does
    bundle.setdefault("location", {})["resolver"] = ..., and a None location
    would 500 there. Omitted key -> setdefault inserts {} -> safe.
    """
    return {"mode": "chat", "topic": "crisis", "reply": CRISIS_REPLY, "plan": None}
