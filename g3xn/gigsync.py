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

Signing in, in this order: GitHub's device flow (a code to type at github.com/login/device) when
the app has an OAuth client id (G3XN_GITHUB_CLIENT_ID, or CLIENT_ID below); a token pasted in
(github.com/settings/tokens, "repo" scope); or the GitHub CLI's own login (`gh auth login`).
The sign-in is kept in ~/.g3xn/github.json. No git needed: it talks to GitHub's API.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import models

API = "https://api.github.com"
CLIENT_ID = ""                  # the g3xn OAuth app's client id, for "Sign in with GitHub" (device flow)
STATE_FILE = os.path.join(models.HOME, "github.json")
REPO_NAME = "g3xn-gigs"
TOKEN_PAGE = "https://github.com/settings/tokens/new?scopes=repo&description=g3xn%20gigs"


class SyncError(RuntimeError):
    pass


def client_id():
    return os.environ.get("G3XN_GITHUB_CLIENT_ID") or CLIENT_ID


def gh_token():
    """The GitHub CLI's token, if it is installed and signed in."""
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
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
    def __init__(self, libraries, state_file=STATE_FILE, api=None, gh=gh_token):
        """libraries: {pedal key: GigLibrary}. api(method, url, body, token) -> (status, JSON):
        tests swap in a fake GitHub. gh: () -> the GitHub CLI's token or None."""
        self.libraries = libraries
        self.state_file = state_file
        self._api_call = api or _http
        self._gh = gh
        self._lock = threading.Lock()
        self._signing_in = None        # {"code", "url", "expires"} while a device-flow sign-in waits
        self._sign_in_problem = ""
        self._login = None
        self._branch = "main"

    # --- signing in ---

    def status(self):
        token, via = self._token()
        out = {"signed_in": False, "via": via, "login": None, "repo": None,
               "can_sign_in": bool(client_id()), "token_page": TOKEN_PAGE,
               "signing_in": self._signing_in and {k: self._signing_in[k] for k in ("code", "url")},
               "problem": self._sign_in_problem, "last": self._state().get("last")}
        if token:
            try:
                out.update(signed_in=True, login=self.login(), repo=self.repo())
            except SyncError as err:
                out["problem"] = str(err)
        return out

    def sign_in(self):
        """Start GitHub's device flow: returns the code to type at the address. A thread waits for
        the user to say yes, then keeps the token."""
        cid = client_id()
        if not cid:
            raise SyncError("this g3xn has no GitHub app to sign in with: paste a token (%s), or run "
                            "`gh auth login`" % TOKEN_PAGE)
        status, r = self._api_call("POST", "https://github.com/login/device/code",
                                   {"client_id": cid, "scope": "repo"}, None)
        if status != 200 or "device_code" not in r:
            raise SyncError("GitHub didn't start the sign-in: %s" % (r.get("error_description") or status))
        self._signing_in = {"code": r["user_code"], "url": r["verification_uri"],
                            "expires": time.time() + r.get("expires_in", 900)}
        self._sign_in_problem = ""
        threading.Thread(target=self._wait_for_yes, args=(cid, r["device_code"], r.get("interval", 5)),
                         name="g3xn-github", daemon=True).start()
        return {"code": r["user_code"], "url": r["verification_uri"]}

    def _wait_for_yes(self, cid, device_code, interval):
        while self._signing_in and time.time() < self._signing_in["expires"]:
            time.sleep(interval)
            _, r = self._api_call("POST", "https://github.com/login/oauth/access_token",
                                  {"client_id": cid, "device_code": device_code,
                                   "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, None)
            if r.get("access_token"):
                self._keep(token=r["access_token"])
                self._signing_in = None
                return
            if r.get("error") == "slow_down":
                interval += 5
            elif r.get("error") != "authorization_pending":
                self._sign_in_problem = r.get("error_description") or r.get("error") or "the sign-in failed"
                break
        self._signing_in = None

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


def _http(method, url, body, token):
    """(status, JSON reply) from GitHub. The device-flow addresses take a form, the API takes JSON."""
    headers = {"Accept": "application/json" if "github.com/login/" in url else "application/vnd.github+json",
               "User-Agent": "g3xn", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        if "github.com/login/" in url:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
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
