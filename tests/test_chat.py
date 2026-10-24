"""Claude in the app and push to talk, with a fake claude, a fake microphone and fake speech-to-text."""
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest

from g3xn.chat import Chat
from g3xn.voice import SAMPLE_RATE, Talk

FAKE_CLAUDE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py")]


class Events:
    def __init__(self):
        self.q = queue.Queue()

    def __call__(self, event):
        self.q.put(event)

    def until(self, test, timeout=10):
        """Events up to and including the first one `test` accepts."""
        seen, deadline = [], time.time() + timeout
        while time.time() < deadline:
            try:
                event = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            seen.append(event)
            if test(event):
                return seen
        raise AssertionError("timed out; saw %r" % seen)


def chat_event(kind):
    return lambda e: e.get("type") == "chat" and e.get("kind") == kind


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.events = Events()
        self.chat = Chat("http://127.0.0.1:9", self.events, claude=FAKE_CLAUDE)
        self.addCleanup(self.chat.close)

    def test_a_message_streams_back_with_the_tools_claude_used(self):
        self.chat.send("less fizzy")
        seen = self.events.until(chat_event("done"))
        self.assertEqual([e["kind"] for e in seen], ["user", "text", "text", "tool", "done"])
        self.assertEqual(seen[3]["name"], "tweak")
        self.assertEqual(seen[-1]["text"], "Treble down on the Twin.")
        self.assertEqual(self.chat.messages[-1], {"role": "claude", "text": "Treble down on the Twin.",
                                                  "tools": [{"name": "tweak", "input": seen[3]["input"]}]})
        self.assertFalse(self.chat.busy)
        self.assertEqual(self.chat.session, "fake-session")

    def test_claude_gets_only_the_g3xn_tools_pointed_at_this_daemon_and_no_api_key(self):
        args_file = os.path.join(tempfile.mkdtemp(), "args.json")
        os.environ["FAKE_CLAUDE_ARGS"], os.environ["ANTHROPIC_API_KEY"] = args_file, "sk-not-for-this"
        self.addCleanup(os.environ.pop, "FAKE_CLAUDE_ARGS")
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY")
        self.chat.send("hi")
        self.events.until(chat_event("done"))
        with open(args_file) as f:
            started = json.load(f)
        argv = started["argv"]
        self.assertEqual(started["daemon"], "http://127.0.0.1:9")
        self.assertFalse(started["api_key"])
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "mcp__g3xn__*")
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertIn("Bash", argv[argv.index("--disallowedTools") + 1].split(","))
        self.assertIn("Read", argv[argv.index("--disallowedTools") + 1].split(","))
        with open(argv[argv.index("--mcp-config") + 1]) as f:
            config = json.load(f)["mcpServers"]["g3xn"]
        self.assertEqual(config["env"], {"G3XN_DAEMON": "http://127.0.0.1:9"})

    def test_the_conversation_resumes_after_a_stop(self):
        self.chat.send("one")
        self.events.until(chat_event("done"))
        self.chat.stop()
        self.chat.send("two")
        self.events.until(chat_event("done"))
        self.assertIn("--resume", self.chat.terminal_command())
        self.assertEqual([m["role"] for m in self.chat.messages], ["user", "claude", "user", "claude"])

    def test_an_error_and_a_crash_are_reported(self):
        self.chat.send("fail")
        self.assertEqual(self.events.until(chat_event("error"))[-1]["text"], "out of credits")
        self.chat.send("die")
        self.events.until(chat_event("error"))
        self.assertFalse(self.chat.busy)

    def test_new_forgets_everything(self):
        self.chat.send("hi")
        self.events.until(chat_event("done"))
        self.chat.new()
        self.assertEqual((self.chat.messages, self.chat.session), ([], None))


class FakeMic:
    def __init__(self, seconds=1.0):
        self.seconds, self.recording = seconds, False

    def start(self):
        self.recording = True

    def stop(self):
        import array
        self.recording = False
        return array.array("f", [0.0] * int(self.seconds * SAMPLE_RATE))


class TalkTest(unittest.TestCase):
    def setUp(self):
        self.events, self.sent = Events(), []
        self.heard = []

    def talk(self, mic="laptop", seconds=1.0, words="more gain on the solo"):
        def transcribe(audio):
            self.heard.append(audio)
            return words
        return Talk(self.events, self.sent.append, mic=mic, recorder=FakeMic(seconds), transcribe=transcribe)

    def test_hold_speak_release_sends_the_words_to_claude(self):
        talk = self.talk()
        talk.press()
        self.assertTrue(talk.recorder.recording)
        talk.release()
        seen = self.events.until(lambda e: e["state"] == "idle")
        self.assertEqual([e["state"] for e in seen], ["listening", "transcribing", "heard", "idle"])
        self.assertEqual(self.sent, ["more gain on the solo"])

    def test_a_tap_or_silence_sends_nothing(self):
        talk = self.talk(seconds=0.1)
        talk.press()
        talk.release()
        self.assertIn("too short", self.events.until(lambda e: e["state"] == "idle")[-1]["problem"])
        talk = self.talk(words="")
        talk.press()
        talk.release()
        self.assertIn("Didn't catch", self.events.until(lambda e: e["state"] == "idle")[-1]["problem"])
        self.assertEqual(self.sent, [])

    def test_the_phone_records_and_sends_the_audio(self):
        talk = self.talk(mic="phone")
        talk.press()
        self.assertFalse(talk.recorder.recording)            # the laptop mic stays off
        talk.release()
        self.assertEqual(talk.audio(b"webm bytes"), "more gain on the solo")
        self.assertEqual(self.heard, [b"webm bytes"])
        self.assertEqual(self.sent, ["more gain on the solo"])

    def test_while_the_stage_is_open_the_words_go_to_it(self):
        talk = self.talk(words="two bars behind")
        talk.stage(True)
        talk.press()
        talk.release()
        seen = self.events.until(lambda e: e["state"] == "idle")
        self.assertEqual([e.get("to") for e in seen if e["state"] == "heard"], ["stage"])
        self.assertEqual(self.sent, [])
        talk.stage(False)
        self.assertEqual(talk.said(" less fizzy "), "less fizzy")
        self.assertEqual(self.sent, ["less fizzy"])
        with self.assertRaises(ValueError):
            talk.said("  ")

    def test_only_known_mics(self):
        with self.assertRaises(ValueError):
            self.talk().set_mic("bluetooth")


try:
    from test_daemon import get_json, start_daemon
    from g3xn.sim import VirtualPedal
    import urllib.request
except ImportError:
    start_daemon = None


@unittest.skipIf(start_daemon is None, "the app extra isn't installed")
class DaemonChatTest(unittest.TestCase):
    def test_chat_and_talk_over_http(self):
        sent = []
        events = Events()
        chat = Chat("http://127.0.0.1:9", events, claude=FAKE_CLAUDE)
        talk = Talk(events, chat.send, recorder=FakeMic(), transcribe=lambda audio: "turn the delay off")
        url, stop = start_daemon(VirtualPedal(), chat=chat, talk=talk)
        self.addCleanup(stop)
        self.addCleanup(chat.close)

        def post(path, body, raw=False):
            data = body if raw else json.dumps(body).encode()
            req = urllib.request.Request(url + path, data=data, method="POST",
                                         headers={"Content-Type": "application/octet-stream" if raw else "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        post("/api/chat", {"text": "less fizzy"})
        events.until(chat_event("done"))
        self.assertEqual(get_json(url + "/api/chat")["messages"][-1]["text"], "Treble down on the Twin.")

        self.assertEqual(post("/api/talk", {"mic": "phone"})["mic"], "phone")
        self.assertEqual(post("/api/talk/audio", b"fake webm", raw=True)["text"], "turn the delay off")
        events.until(chat_event("done"))
        self.assertEqual(chat.messages[-2]["text"], "turn the delay off")


if __name__ == "__main__":
    unittest.main()
