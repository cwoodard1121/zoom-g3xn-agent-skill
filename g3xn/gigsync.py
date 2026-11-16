"""Gigs on GitHub: send this computer's gigs to a private repo, and get them on another computer.

    sync = GigSync({"g3xn": GigLibrary(...), "b1xfour": GigLibrary(...)})
    sync.status()        # signed in? as whom? which repo?
    sync.send()          # every gig here goes up
    sync.get()           # every gig there comes down

The repo is private and is <your login>/g3xn-gigs unless you name another; it is made on the
first send. Gigs live in it as gigs/<pedal>/<gig id>.json. What a gig loaded into this pedal's
slots ("loaded") stays on this computer: another pedalboard's slots are its own.

It works file by file, both ways:
  send  every gig here goes up, and this computer's version wins. A gig deleted here since the
        last sync is deleted there.
  get   every gig there comes down, and GitHub's version wins (the one it replaces is moved to
        the gigs' "deleted" folder). A gig deleted there since the last sync is moved to
        "deleted" here.

Signing in: the GitHub CLI's own login. "Sign in with GitHub" runs `gh auth login --web` for
the user (a code to type at github.com/login/device), so g3xn needs no GitHub app of its own.
Without the CLI, a token pasted in (github.com/settings/tokens, "repo" scope) works too, and is
kept in ~/.g3xn/github.json. No git needed: it talks to GitHub's API.
"""
import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import models

API = "https://api.github.com"
STATE_FILE = os.path.join(models.HOME, "github.json")
REPO_NAME = "g3xn-gigs"
TOKEN_PAGE = "https://github.com/settings/tokens/new?scopes=repo&description=g3xn%20gigs"
GH_PAGE = "https://cli.github.com"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CODE_LINE = re.compile(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})")
PAGE_LINE = re.compile(r"(https://github\.com/login/device)\b")
COLOUR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CODE_WAIT = 30                  # seconds for the GitHub CLI to print its code


class SyncError(RuntimeError):
    pass


def find_gh():
    """The GitHub CLI's program: on PATH, or where its installers put it (it may be installed
    while g3xn runs, and then g3xn's PATH doesn't have it yet)."""
    found = shutil.which("gh")
    if found:
        return found
    env = os.environ.get
    places = [os.path.join(env("ProgramFiles", r"C:\Program Files"), "GitHub CLI", "gh.exe"),
              os.path.join(env("LOCALAPPDATA", ""), "Programs", "GitHub CLI", "gh.exe"),
              os.path.join(env("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "gh.exe"),
              os.path.join(os.path.expanduser("~"), "scoop", "shims", "gh.exe")] if os.name == "nt" else \
             ["/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"]
    return next((p for p in places if os.path.isfile(p)), None)


def has_gh():
    return bool(find_gh())


def _gh_env():
    """The CLI's environment, without colour: its codes would hide the one-time code from CODE_LINE."""
    env = {k: v for k, v in os.environ.items() if k not in ("CLICOLOR_FORCE", "GH_FORCE_TTY")}
    env["NO_COLOR"] = "1"
    return env


def gh_login():
    """Start `gh auth login --web` with no terminal: it prints a one-time code and the page to type
    it at, then waits until the user says yes there (or the code runs out, after 15 minutes).
    None when the GitHub CLI isn't installed. No --git-protocol: that would overwrite the user's."""
    gh = find_gh()
    if not gh:
        return None
    return subprocess.Popen([gh, "auth", "login", "--hostname", "github.com", "--web", "--scopes", "repo"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW, env=_gh_env())


def gh_token():
    """The GitHub CLI's token, if it is installed and signed in."""
    gh = find_gh()
    if not gh:
        return None
    try:
        out = subprocess.run([gh, "auth", "token", "--hostname", "github.com"], capture_output=True, text=True,
                             timeout=10, creationflags=NO_WINDOW, env=_gh_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def portable(gig):
    """A gig as it goes to GitHub: without what was loaded into this pedal's slots."""
    return {k: v for k, v in gig.items() if k != "loaded"}


def as_bytes(gig):
    return (json.dumps(portable(gig), indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def blob_sha(data):
    """The id git gives a file's content, so a file is only sent or fetched when it changed."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class GigSync:
    def __init__(self, libraries, state_file=STATE_FILE, api=None, gh=gh_token, login=gh_login,
                 can_login=has_gh, open_page=webbrowser.open):
        """libraries: {pedal key: GigLibrary}. api(method, url, body, token) -> (status, JSON):
        tests swap in a fake GitHub. gh: () -> the GitHub CLI's token or None. login: () -> a
        running `gh auth login --web` (a Popen) or None. can_login: () -> the CLI is installed.
        open_page(url): show the page where the code is typed."""
        self.libraries = libraries
        self.state_file = state_file
        self._api_call = api or _http
        self._gh = gh
        self._start_login = login
        self._can_login = can_login
        self._open_page = open_page
        self._lock = threading.Lock()
        self._signing_in = None        # {"code", "url"} while the GitHub CLI waits for the user
        self._login_process = None
        self._closed = False
        self._sign_in_problem = ""
        self._login = None
        self._branch = "main"

    # --- signing in ---

    def status(self):
        """Signed in or not (a token GitHub rejects is not signed in), the sign-in waiting for the
        user if there is one, and the last send or get."""
        token, via = self._token()
        signing = self._signing_in
        out = {"signed_in": False, "via": via, "login": None, "repo": None,
               "can_sign_in": bool(self._can_login()), "token_page": TOKEN_PAGE, "gh_page": GH_PAGE,
               "signing_in": None, "problem": self._sign_in_problem, "last": self._state().get("last")}
        if token:
            try:
                out.update(signed_in=True, login=self.login(), repo=self.repo(), problem="")
            except SyncError as err:
                out["problem"] = str(err)
        if signing and not out["signed_in"]:
            out["signing_in"] = dict(signing)
        return out

    def sign_in(self):
        """Sign in through the GitHub CLI: start `gh auth login --web`, open the page where its
        one-time code is typed, and return {"code", "url"}. A thread waits for the CLI to finish;
        from then on its login is the one used (a pasted token kept before is dropped). A second
        call while it waits returns the same code. close() stops it, even before the code shows."""
        with self._lock:
            if self._signing_in:
                return dict(self._signing_in)
            if self._closed:
                raise SyncError("g3xn is closing")
            proc = self._start_login()
            if proc is None:
                raise SyncError("install the GitHub CLI (%s) to sign in, or paste a token" % GH_PAGE)
            self._login_process = proc             # close() can stop it while the code is awaited
            self._sign_in_problem = ""
            lines = queue.Queue()
            threading.Thread(target=_read_lines, args=(proc, lines), name="g3xn-gh-out", daemon=True).start()
            code, url, said = None, None, []
            deadline = time.monotonic() + CODE_WAIT
            while not (code and url):
                try:
                    line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if line is None:                   # the CLI stopped without a code
                    break
                line = COLOUR.sub("", line)
                said.append(line.strip())
                found = CODE_LINE.search(line)
                code = code or (found and found.group(1))
                found = PAGE_LINE.search(line)
                url = url or (found and found.group(1))
            if not (code and url) or self._closed:
                _stop(proc)
                self._login_process = None
                if self._closed:
                    raise SyncError("g3xn is closing")
                told = " ".join(s for s in said if s)[-300:]
                raise SyncError("the GitHub CLI didn't start a sign-in%s" % (": " + told if told else ""))
            self._signing_in = {"code": code, "url": url}
            self._login = None
        threading.Thread(target=self._wait_for_gh, args=(proc, lines), name="g3xn-github", daemon=True).start()
        try:
            self._open_page(url)
        except Exception:                         # no browser: the app shows the page as a link
            pass
        return {"code": code, "url": url}

    def _wait_for_gh(self, proc, lines):
        said = []
        while True:
            line = lines.get()
            if line is None:
                break
            said.append(COLOUR.sub("", line).strip())
        ok = proc.wait() == 0
        with self._lock:
            self._login = None
            if ok:
                # the CLI's login is the one to use now: a pasted token kept before would win over
                # it in _token(), and may be the very one GitHub rejects
                state = self._state()
                if state.pop("token", None) is not None:
                    self._save(state)
                self._sign_in_problem = ""
            elif not self._closed:
                last = next((s for s in reversed(said) if s), "")
                self._sign_in_problem = "the GitHub sign-in didn't finish" + (": " + last if last else "")
            self._signing_in = None
            self._login_process = None

    def close(self):
        """Stop a GitHub CLI sign-in still waiting, or still starting (the app is closing)."""
        self._closed = True
        proc = self._login_process
        if proc is not None:
            _stop(proc)

    def use_token(self, token):
        """Sign in with a token pasted in (it needs the "repo" scope)."""
        token = (token or "").strip()
        status, r = self._api_call("GET", API + "/user", None, token)
        if status != 200:
            raise SyncError("GitHub didn't take that token (%s)" % (r.get("message") or status))
        self._keep(token=token)
        self._login = r["login"]
        return self.status()

    def sign_out(self):
        """Forget the token g3xn kept (the GitHub CLI's own login stays)."""
        state = self._state()
        state.pop("token", None)
        self._save(state)
        self._login = None
        return self.status()

    def set_repo(self, repo):
        """Use another repo ("owner/name", or just "name" in your account); "" goes back to the default."""
        repo = (repo or "").strip().strip("/")
        if repo.startswith("https://github.com/"):
            repo = repo[len("https://github.com/"):].removesuffix(".git")
        if repo and not all(part and all(c.isalnum() or c in "-_." for c in part) for part in repo.split("/")[:2]):
            raise SyncError("a repo is owner/name, e.g. %s" % REPO_NAME)
        self._keep(repo=repo or None)
        return self.status()

    def login(self):
        if not self._login:
            self._login = self._call("GET", "/user")["login"]
        return self._login

    def repo(self):
        repo = self._state().get("repo") or REPO_NAME
        return repo if "/" in repo else "%s/%s" % (self.login(), repo)

    # --- send and get ---

    def send(self):
        """Every gig here goes up. Returns what changed there."""
        with self._lock:
            repo = self._ensure_repo()
            there = self._files(repo)
            synced = self._state().get("synced", {})
            sent, deleted, same = [], [], 0
            for key, lib in self.libraries.items():
                here = {g["id"]: lib.get(g["id"]) for g in lib.list()}
                for gig_id, gig in here.items():
                    path = "gigs/%s/%s.json" % (key, gig_id)
                    data = as_bytes(gig)
                    if there.get(path) == blob_sha(data):
                        same += 1
                        continue
                    body = {"message": "%s gig: %s" % ("Update" if path in there else "Add", gig.get("name", gig_id)),
                            "content": base64.b64encode(data).decode()}
                    if path in there:
                        body["sha"] = there[path]
                    self._call("PUT", "/repos/%s/contents/%s" % (repo, _quote(path)), body)
                    sent.append(gig.get("name", gig_id))
                for gig_id in set(synced.get(key, [])) - set(here):
                    path = "gigs/%s/%s.json" % (key, gig_id)
                    if path in there:            # deleted here since the last sync
                        self._call("DELETE", "/repos/%s/contents/%s" % (repo, _quote(path)),
                                   {"message": "Delete gig %s" % gig_id, "sha": there[path]})
                        deleted.append(gig_id)
            return self._done("send", repo, sent=sent, deleted=deleted, unchanged=same)

    def get(self):
        """Every gig there comes down. Returns what changed here."""
        with self._lock:
            repo = self._ensure_repo(make=False)
            there = self._files(repo)
            synced = self._state().get("synced", {})
            got, deleted, same = [], [], 0
            for key, lib in self.libraries.items():
                prefix = "gigs/%s/" % key
                remote = {p[len(prefix):-5]: sha for p, sha in there.items()
                          if p.startswith(prefix) and p.endswith(".json") and "/" not in p[len(prefix):]}
                here = {g["id"]: lib.get(g["id"]) for g in lib.list()}
                for gig_id, sha in remote.items():
                    mine = here.get(gig_id)
                    if mine is not None and blob_sha(as_bytes(mine)) == sha:
                        same += 1
                        continue
                    gig = json.loads(self._blob(repo, sha))
                    gig["id"] = gig_id
                    if mine is not None:
                        lib.delete(gig_id)        # the version it replaces goes to "deleted"
                        if mine.get("loaded"):
                            gig["loaded"] = mine["loaded"]    # what this pedal holds stays known
                    lib.save(gig)
                    got.append(gig.get("name", gig_id))
                for gig_id in set(synced.get(key, [])) - set(remote):
                    if gig_id in here:            # deleted there since the last sync
                        lib.delete(gig_id)
                        deleted.append(here[gig_id].get("name", gig_id))
            return self._done("get", repo, got=got, deleted=deleted, unchanged=same)

    # --- GitHub ---

    def _ensure_repo(self, make=True):
        repo = self.repo()
        status, r = self._api_call("GET", API + "/repos/" + repo, None, self._need_token())
        if status == 200:
            self._branch = r.get("default_branch") or "main"
            return repo
        if status != 404:
            raise SyncError("GitHub: %s" % (r.get("message") or status))
        owner, name = repo.split("/", 1)
        if not make:
            raise SyncError("there are no gigs on GitHub yet (%s doesn't exist). Send some first." % repo)
        if owner.lower() != self.login().lower():
            raise SyncError("%s doesn't exist, and g3xn only makes repos in your own account" % repo)
        made = self._call("POST", "/user/repos", {"name": name, "private": True, "auto_init": True,
                                                  "description": "Gigs from the g3xn app"})
        self._branch = made.get("default_branch") or "main"
        return repo

    def _files(self, repo):
        """{path: blob sha} of every file in the repo's default branch."""
        status, r = self._api_call("GET", API + "/repos/%s/git/trees/%s?recursive=1" % (repo, _quote(self._branch)),
                                   None, self._need_token())
        if status in (404, 409):                  # an empty repo
            return {}
        if status != 200:
            raise SyncError("GitHub: %s" % (r.get("message") or status))
        return {t["path"]: t["sha"] for t in r.get("tree", []) if t.get("type") == "blob"}

    def _blob(self, repo, sha):
        r = self._call("GET", "/repos/%s/git/blobs/%s" % (repo, sha))
        return base64.b64decode(r["content"])

    def _call(self, method, path, body=None):
        status, r = self._api_call(method, API + path, body, self._need_token())
        if status >= 300:
            raise SyncError("GitHub: %s" % (r.get("message") or status))
        return r

    def _need_token(self):
        token, _ = self._token()
        if not token:
            raise SyncError("sign in to GitHub first")
        return token

    def _token(self):
        """(token, where it came from): g3xn's own sign-in, else the GitHub CLI's."""
        token = self._state().get("token")
        if token:
            return token, "app"
        token = self._gh() if self._gh else None
        return (token, "gh") if token else (None, None)

    # --- the state file ---

    def _done(self, action, repo, **result):
        state = self._state()
        state["synced"] = {key: sorted(g["id"] for g in lib.list()) for key, lib in self.libraries.items()}
        state["last"] = dict(result, action=action, repo=repo, time=time.time())
        self._save(state)
        return state["last"]

    def _keep(self, **changes):
        state = self._state()
        state.update(changes)
        self._save({k: v for k, v in state.items() if v is not None})

    def _state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, state):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, self.state_file)


def _quote(path):
    return urllib.parse.quote(path, safe="/")


def _read_lines(proc, lines):
    """Pass the GitHub CLI's output on line by line; None when it closes."""
    try:
        for line in proc.stdout:
            lines.put(line)
    except (OSError, ValueError):
        pass
    lines.put(None)


def _stop(proc):
    try:
        proc.kill()
    except OSError:
        pass


def _http(method, url, body, token):
    """(status, JSON reply) from GitHub's API."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "g3xn", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else {}
        except ValueError:
            return err.code, {"message": raw.decode("utf-8", "replace")[:200]}
    except urllib.error.URLError as err:
        raise SyncError("can't reach GitHub: %s" % err.reason) from err
