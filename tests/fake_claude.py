"""Stands in for `claude -p --input-format stream-json --output-format stream-json`.

For each message it answers with a session id, the reply written in two parts, one g3xn
tool call and a result. A message saying "fail" gets an error result; "die" exits mid-answer.
Writes the arguments it was started with to FAKE_CLAUDE_ARGS, if set.
"""
import json
import os
import sys

if os.environ.get("FAKE_CLAUDE_ARGS"):
    with open(os.environ["FAKE_CLAUDE_ARGS"], "w") as f:
        json.dump({"argv": sys.argv[1:], "daemon": os.environ.get("G3XN_DAEMON"),
                   "api_key": "ANTHROPIC_API_KEY" in os.environ}, f)


def say(event):
    print(json.dumps(event), flush=True)


for line in sys.stdin:
    text = json.loads(line)["message"]["content"]
    say({"type": "system", "subtype": "init", "session_id": "fake-session"})
    if text == "die":
        sys.exit(3)
    if text == "fail":
        say({"type": "result", "is_error": True, "result": "out of credits", "session_id": "fake-session"})
        continue
    for part in ("Treble down ", "on the Twin."):
        say({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": part}}})
    say({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "mcp__g3xn__tweak", "input": {"changes": [{"effect": 2, "knob": "Treble", "value": 45}]}}]}})
    say({"type": "result", "is_error": False, "result": "Treble down on the Twin.", "session_id": "fake-session"})
