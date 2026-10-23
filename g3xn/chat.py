"""Claude in the app: the user's own Claude Code, run headless with the g3xn tools.

One `claude -p` process per conversation, fed and read as stream-json. It uses the
login Claude Code already has (ANTHROPIC_API_KEY is taken out of its environment so
an unrelated key never gets billed), and only the g3xn MCP server, pointed at this
daemon through G3XN_DAEMON so it can never go round the app to the pedal.

Everything Claude says and does goes out as events:

    {"type": "chat", "kind": "user",  "text": "less fizzy"}
    {"type": "chat", "kind": "text",  "delta": "Treble down"}       (as it's written)
    {"type": "chat", "kind": "tool",  "name": "tweak", "input": {...}}
    {"type": "chat", "kind": "done",  "text": "Treble down on the Twin..."}
    {"type": "chat", "kind": "error", "text": "..."}

and `messages` keeps the conversation for a page that opens later.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

TOOL_PREFIX = "mcp__g3xn__"
# Claude Code's own tools, off in the app's chat: it's there for the pedal, and a misheard
# footswitch request mustn't be able to run commands or read the user's files.
BUILT_INS = ("Bash", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep",
             "WebFetch", "WebSearch", "Agent", "Task")

SYSTEM_PROMPT = """You are inside the g3xn app, next to the user's Zoom G3Xn guitar pedal.
They are holding a guitar, often talking through a push-to-talk footswitch, so keep replies
to a sentence or two and do the change rather than describing it. Work on the scratch slot:
audition, then tweak while they play. Say what you changed in plain words with the numbers
("Treble 52 to 45 on the Twin"). Never save over one of their slots unless they say to.
If they say "undo", put back what you last changed."""


def find_claude():
    """The Claude Code executable: G3XN_CLAUDE, the native installer's, npm's, or on PATH.
    npm's claude.cmd is skipped for the claude.exe it wraps, so stdin/stdout stay ours."""
    candidates = [
        os.environ.get("G3XN_CLAUDE"),
        os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe"),
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"),
        shutil.which("claude.exe") if os.name == "nt" else shutil.which("claude"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


class ChatError(RuntimeError):
    pass


class Chat:
    def __init__(self, daemon_url, emit, claude=None, cwd=None):
        """daemon_url: this daemon, for the g3xn tools. emit(event): tell the app.
        claude: the command to run (default: find_claude()); a list runs as is (tests)."""
        self.daemon_url, self.emit = daemon_url, emit
        self.claude = claude
        self.cwd = cwd          # None: the chat's own empty folder (no project settings get picked up)
        self.session = None          # Claude Code's session id, to resume or open in a terminal
        self.messages = []           # [{"role": "user"|"claude", "text", "tools": [...]}]
        self.busy = False
        self._proc = None
        self._lock = threading.Lock()
        self._reply = None           # the Claude message being written

    # --- the conversation ---

    def send(self, text):
        text = (text or "").strip()
        if not text:
            raise ValueError("say something to Claude")
        with self._lock:
            proc = self._process()
            self.messages.append({"role": "user", "text": text})
            self._reply = {"role": "claude", "text": "", "tools": []}
            self.messages.append(self._reply)
            self.busy = True
            line = {"type": "user", "message": {"role": "user", "content": text}}
            try:
                proc.stdin.write(json.dumps(line) + "\n")
                proc.stdin.flush()
            except OSError as err:
                self._close()
                self.busy = False
                raise ChatError("Claude stopped: %s" % err) from err
        self.emit({"type": "chat", "kind": "user", "text": text})

    def stop(self):
        """Stop what Claude is doing. The conversation carries on with the next message."""
        with self._lock:
            was_busy = self.busy
            self._close()
            self.busy = False
        if was_busy:
            self._finish("Stopped.")

    def new(self):
        """Forget the conversation and start a fresh one."""
        with self._lock:
            self._close()
            self.session, self.messages, self.busy, self._reply = None, [], False, None
        self.emit({"type": "chat", "kind": "new"})

    def terminal_command(self):
        """The command that opens this conversation in a full Claude Code terminal session."""
        cmd = self._base_command(interactive=True)
        if self.session:
            cmd += ["--resume", self.session]
        return cmd

    def open_terminal(self):
        """Hand the conversation to Claude Code in a terminal window (the headless one stops,
        since a session can't be written by two processes)."""
        self.stop()
        cmd = self.terminal_command()
        home = self.cwd or os.path.expanduser("~")       # the user's own session, with their tools
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "g3xn - Claude Code"] + cmd, cwd=home, env=self._env())
        else:
            subprocess.Popen(cmd, cwd=home, env=self._env(), start_new_session=True)
        return {"session": self.session, "command": cmd}

    def info(self):
        return {"busy": self.busy, "session": self.session, "messages": self.messages,
                "available": bool(self._command_base())}

    def close(self):
        with self._lock:
            self._close()

    # --- the claude process ---

    def _command_base(self):
        if isinstance(self.claude, list):
            return list(self.claude)
        path = self.claude or find_claude()
        return [path] if path else None

    def _base_command(self, interactive=False):
        base = self._command_base()
        if not base:
            raise ChatError("Claude Code isn't installed on this computer (or set G3XN_CLAUDE to it)")
        config, prompt = self._files()
        headless = [] if interactive else ["-p", "--input-format", "stream-json", "--output-format", "stream-json",
                                           "--verbose", "--include-partial-messages", "--permission-prompts", "none",
                                           "--disallowedTools", ",".join(BUILT_INS)]
        return base + headless + ["--mcp-config", config, "--strict-mcp-config",
                                  "--allowedTools", TOOL_PREFIX + "*",
                                  "--append-system-prompt-file", prompt]

    def _files(self):
        """The MCP config and system prompt, as files: they survive being passed through a
        terminal's command line, where JSON and quotes don't."""
        if not getattr(self, "_folder", None):
            self._folder = tempfile.mkdtemp(prefix="g3xn-claude-")
        config = os.path.join(self._folder, "mcp.json")
        prompt = os.path.join(self._folder, "prompt.md")
        with open(config, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"g3xn": {"command": sys.executable, "args": ["-m", "g3xn.mcp_server"],
                                               "env": {"G3XN_DAEMON": self.daemon_url}}}}, f)
        with open(prompt, "w", encoding="utf-8") as f:
            f.write(SYSTEM_PROMPT)
        return config, prompt

    def _env(self):
        env = dict(os.environ, G3XN_DAEMON=self.daemon_url)
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def _process(self):
        if self._proc and self._proc.poll() is None:
            return self._proc
        cmd = self._base_command()
        if self.session:
            cmd += ["--resume", self.session]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        errors = tempfile.TemporaryFile()               # what it says when it fails
        self._proc = subprocess.Popen(cmd, cwd=self.cwd or self._folder, env=self._env(), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=errors,
                                      text=True, encoding="utf-8", bufsize=1, creationflags=flags)
        threading.Thread(target=self._read, args=(self._proc, errors), name="g3xn-chat", daemon=True).start()
        return self._proc

    def _close(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    def _read(self, proc, errors):
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if proc is self._proc:
                self._handle(event)
        if proc is self._proc and self.busy:          # it died mid-answer
            proc.wait()
            errors.seek(0)
            why = errors.read().decode("utf-8", "replace").strip().splitlines()
            self._proc = None
            self._fail(why[-1] if why else "Claude stopped unexpectedly")
        errors.close()

    def _handle(self, event):
        kind = event.get("type")
        if event.get("session_id"):
            self.session = event["session_id"]
        if kind == "stream_event":
            delta = event.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta" and self._reply is not None:
                self._reply["text"] += delta["text"]
                self.emit({"type": "chat", "kind": "text", "delta": delta["text"]})
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and self._reply is not None:
                    name = block.get("name", "")
                    if not name.startswith(TOOL_PREFIX):       # Claude Code's own (finding tools and so on)
                        continue
                    tool = {"name": name[len(TOOL_PREFIX):], "input": block.get("input", {})}
                    self._reply["tools"].append(tool)
                    self.emit(dict(tool, type="chat", kind="tool"))
                elif block.get("type") == "text" and self._reply is not None and not self._reply["text"]:
                    self._reply["text"] = block.get("text", "")    # no partial messages came
        elif kind == "result":
            if event.get("is_error"):
                self._fail(event.get("result") or "Claude couldn't answer")
            else:
                self._finish(event.get("result"))

    def _finish(self, text):
        self.busy = False
        reply, self._reply = self._reply, None
        if reply is not None and text and not reply["text"]:
            reply["text"] = text
        self.emit({"type": "chat", "kind": "done", "text": reply["text"] if reply else text or ""})

    def _fail(self, text):
        self.busy = False
        reply, self._reply = self._reply, None
        if reply is not None:
            reply["error"] = text
        self.emit({"type": "chat", "kind": "error", "text": text})
