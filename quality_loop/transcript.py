"""Reading a room's stream-json transcript.

`claude -p --output-format stream-json --verbose` writes one JSON object per
line. Everything here reads that record rather than the room's account of what
it did, and everything here is tolerant of it: a line that does not parse, an
event whose ``message`` is a plain string, a ``content`` that is a string
rather than a list of parts. A refusal arrives in exactly that shape - XeFM's
first parser assumed a dict and crashed on every real room.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Iterator


def events(transcript: pathlib.Path) -> Iterator[dict]:
    """Every event in the transcript that parses as a JSON object."""
    try:
        text = pathlib.Path(transcript).read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def parts(event: dict) -> list[dict]:
    """The content parts of an event's message, or none.

    None when the message is missing, is a string, or carries its content as a
    string: those events say nothing about a tool call.
    """
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, dict)]


def result_text(content) -> str:
    """A tool result's content as text, whichever shape it came in."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content
                         if isinstance(part, dict))
    return str(content or "")


@dataclasses.dataclass
class ToolCall:
    """One tool call, with what came back."""
    id: str
    name: str
    input: dict
    result: str = ""
    is_error: bool = False
    answered: bool = False


def tool_calls(transcript: pathlib.Path) -> list[ToolCall]:
    """Every tool call in the transcript, in order, paired with its result."""
    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    for event in events(transcript):
        kind = event.get("type")
        for part in parts(event):
            if kind == "assistant" and part.get("type") == "tool_use":
                given = part.get("input")
                call = ToolCall(str(part.get("id", "")), str(part.get("name", "")),
                                given if isinstance(given, dict) else {})
                calls.append(call)
                by_id[call.id] = call
            elif kind == "user" and part.get("type") == "tool_result":
                call = by_id.get(str(part.get("tool_use_id", "")))
                if call is not None:
                    call.result = result_text(part.get("content"))
                    call.is_error = bool(part.get("is_error"))
                    call.answered = True
    return calls


def init_event(transcript: pathlib.Path) -> dict | None:
    """The session's init event, wherever it is.

    Looked for rather than assumed to be first: a rate_limit_event can come
    ahead of it, and reading line one as the init event once disqualified a
    clean run.
    """
    return next((e for e in events(transcript)
                 if e.get("type") == "system" and e.get("subtype") == "init"), None)


def final_reply(transcript: pathlib.Path) -> str:
    """The session's last word: the result event's text."""
    replies = [e.get("result", "") for e in events(transcript)
               if e.get("type") == "result"]
    return str(replies[-1]) if replies else ""


def result_event(transcript: pathlib.Path) -> dict | None:
    """The last result event: turns, duration, cost, and whether it errored."""
    found = [e for e in events(transcript) if e.get("type") == "result"]
    return found[-1] if found else None


def lost_the_model(transcript: pathlib.Path) -> bool:
    """Whether the session ended because it could not reach the model.

    A machine that sleeps with a room open wakes with no network, and the
    session's last word is "API Error: Can't reach the API server". Its result
    event still says `success`, with `is_error` set, and everything the run
    left behind looks like an ordinary end. A run the model never finished
    measured the network, not the product.
    """
    for event in events(transcript):
        if event.get("type") == "assistant" and event.get("error"):
            return True
        if event.get("type") == "result" and event.get("is_error"):
            return True
    return False
