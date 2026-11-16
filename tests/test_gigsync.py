"""Gigs on GitHub, against a fake GitHub: two computers send and get each other's gigs."""
import pin_mode  # noqa: F401  (G3Xn mode for these tests)
import base64
import json
import os
import re
import tempfile
import unittest

from g3xn.gig import GigLibrary
from g3xn.gigsync import GigSync, SyncError, blob_sha


class FakeGitHub:
    """Just enough of GitHub's API: one user, repos, the default branch's files, the device flow."""

    def __init__(self, login="player", token="t0ken"):
        self.login, self.token = login, token
        self.repos = {}                  # "owner/name" -> {path: bytes}
        self.private = {}
        self.calls = []
        self.device_polls = 0

    def __call__(self, method, url, body, token):
        self.calls.append((method, url))
        if url == "https://github.com/login/device/code":
            return 200, {"device_code": "dev", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device",
                         "interval": 0, "expires_in": 60}
        if url == "https://github.com/login/oauth/access_token":
            self.device_polls += 1
            return 200, ({"error": "authorization_pending"} if self.device_polls < 2 else {"access_token": self.token})
        if token != self.token:
            return 401, {"message": "Bad credentials"}
        path = url.split("https://api.github.com", 1)[1]
        if path == "/user":
            return 200, {"login": self.login}
        if path == "/user/repos" and method == "POST":
            full = "%s/%s" % (self.login, body["name"])
            self.repos[full] = {"README.md": b"# gigs\n"} if body.get("auto_init") else {}
            self.private[full] = body.get("private")
            return 201, {"full_name": full, "default_branch": "main"}
        m = re.fullmatch(r"/repos/([^/]+/[^/]+)(.*)", path.split("?")[0])
        repo, rest = m.group(1), m.group(2)
        if repo not in self.repos:
            return 404, {"message": "Not Found"}
        files = self.repos[repo]
        if rest == "":
            return 200, {"full_name": repo, "default_branch": "main"}
        if rest == "/git/trees/main":
            if not files:
                return 409, {"message": "Git Repository is empty."}
            return 200, {"tree": [{"path": p, "type": "blob", "sha": blob_sha(d)} for p, d in files.items()]}
        if rest.startswith("/git/blobs/"):
            sha = rest.rsplit("/", 1)[1]
            data = next(d for d in files.values() if blob_sha(d) == sha)
            return 200, {"content": base64.b64encode(data).decode(), "encoding": "base64"}
        if rest.startswith("/contents/"):
            file = rest[len("/contents/"):]
            if method == "PUT":
                if file in files and body.get("sha") != blob_sha(files[file]):
                    return 409, {"message": "sha does not match"}
                files[file] = base64.b64decode(body["content"])
                return 200 if body.get("sha") else 201, {}
            if method == "DELETE":
                if body.get("sha") != blob_sha(files.get(file, b"")):
                    return 409, {"message": "sha does not match"}
                del files[file]
                return 200, {}
        return 404, {"message": "Not Found"}


def computer(github, gh=None):
    """A computer with its own gig folders and its own sign-in file."""
    home = tempfile.mkdtemp()
    libs = {"g3xn": GigLibrary(os.path.join(home, "gigs")), "b1xfour": GigLibrary(os.path.join(home, "b1xfour", "gigs"))}
    return GigSync(libs, state_file=os.path.join(home, "github.json"), api=github, gh=lambda: gh), libs


FRIDAY = {"name": "Friday", "start_slot": 100, "patches": [{"song": "Sultans", "from_slot": 1, "lyrics": "Way on down south"}]}


class GigSyncTest(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.home, self.home_libs = computer(self.github)
        self.gig_pc, self.gig_libs = computer(self.github, gh=self.github.token)     # signed in with the GitHub CLI

    def test_not_signed_in(self):
        status = self.home.status()
        self.assertEqual((status["signed_in"], status["via"]), (False, None))
        self.assertIn("settings/tokens", status["token_page"])
        with self.assertRaises(SyncError):
            self.home.send()

    def test_a_bad_token_is_refused(self):
        with self.assertRaises(SyncError):
            self.home.use_token("nope")

    def test_send_makes_a_private_repo_and_get_brings_the_gigs_to_another_computer(self):
        self.home.use_token(self.github.token)
        mine = self.home_libs["g3xn"].save(dict(FRIDAY, loaded={"time": 1, "slots": []}))
        bass = self.home_libs["b1xfour"].save({"name": "Bass night", "start_slot": 42, "patches": []})
        sent = self.home.send()
        self.assertEqual(sorted(sent["sent"]), ["Bass night", "Friday"])
        self.assertTrue(self.github.private["player/g3xn-gigs"])
        files = self.github.repos["player/g3xn-gigs"]
        stored = json.loads(files["gigs/g3xn/%s.json" % mine["id"]])
        self.assertNotIn("loaded", stored)                  # this pedal's slots stay on this computer
        self.assertEqual(stored["patches"][0]["lyrics"], "Way on down south")

        status = self.gig_pc.status()
        self.assertEqual((status["signed_in"], status["via"], status["repo"]), (True, "gh", "player/g3xn-gigs"))
        got = self.gig_pc.get()
        self.assertEqual(sorted(got["got"]), ["Bass night", "Friday"])
        self.assertEqual(self.gig_libs["g3xn"].get(mine["id"])["patches"], FRIDAY["patches"])
        self.assertEqual(self.gig_libs["b1xfour"].get(bass["id"])["name"], "Bass night")
        self.assertEqual(self.gig_pc.get()["unchanged"], 2)  # nothing new: nothing fetched
        self.assertEqual(self.home.send()["sent"], [])

    def test_changes_and_deletes_go_both_ways(self):
        self.home.use_token(self.github.token)
        mine = self.home_libs["g3xn"].save(FRIDAY)
        other = self.home_libs["g3xn"].save({"name": "Saturday", "start_slot": 110, "patches": []})
        self.home.send()
        self.gig_pc.get()

        # the gig computer changes Friday and keeps what it loaded; deletes Saturday; sends
        there = self.gig_libs["g3xn"].get(mine["id"])
        self.gig_libs["g3xn"].save(dict(there, name="Friday late", loaded={"time": 5, "slots": []}))
        self.gig_libs["g3xn"].delete(other["id"])
        result = self.gig_pc.send()
        self.assertEqual((result["sent"], result["deleted"]), (["Friday late"], [other["id"]]))

        # home gets it: Friday is renamed, Saturday goes to "deleted", home's old Friday is kept there too
        self.home_libs["g3xn"].save(dict(self.home_libs["g3xn"].get(mine["id"]), loaded={"time": 9, "slots": []}))
        got = self.home.get()
        self.assertEqual((got["got"], got["deleted"]), (["Friday late"], ["Saturday"]))
        friday = self.home_libs["g3xn"].get(mine["id"])
        self.assertEqual((friday["name"], friday["loaded"]["time"]), ("Friday late", 9))
        self.assertEqual([g["id"] for g in self.home_libs["g3xn"].list()], [mine["id"]])
        self.assertEqual(len(os.listdir(os.path.join(self.home_libs["g3xn"].folder, "deleted"))), 2)

    def test_get_before_anything_was_sent(self):
        self.home.use_token(self.github.token)
        with self.assertRaises(SyncError) as err:
            self.home.get()
        self.assertIn("Send some first", str(err.exception))

    def test_another_repo_and_sign_out(self):
        self.home.use_token(self.github.token)
        self.assertEqual(self.home.set_repo("band-gigs")["repo"], "player/band-gigs")
        self.home_libs["g3xn"].save(FRIDAY)
        self.home.send()
        self.assertIn("player/band-gigs", self.github.repos)
        with self.assertRaises(SyncError):
            self.home.set_repo("not a repo!")
        self.assertEqual(self.home.sign_out()["signed_in"], False)

    def test_device_flow_sign_in(self):
        saved = os.environ.get("G3XN_GITHUB_CLIENT_ID")
        os.environ["G3XN_GITHUB_CLIENT_ID"] = "client"
        try:
            self.assertTrue(self.home.status()["can_sign_in"])
            started = self.home.sign_in()
            self.assertEqual(started, {"code": "ABCD-1234", "url": "https://github.com/login/device"})
            for _ in range(200):
                if self.home.status()["signed_in"]:
                    break
                import time
                time.sleep(0.01)
            status = self.home.status()
            self.assertEqual((status["signed_in"], status["via"], status["login"]), (True, "app", "player"))
        finally:
            if saved is None:
                os.environ.pop("G3XN_GITHUB_CLIENT_ID")
            else:
                os.environ["G3XN_GITHUB_CLIENT_ID"] = saved

    def test_without_an_app_sign_in_names_the_other_ways(self):
        saved = os.environ.pop("G3XN_GITHUB_CLIENT_ID", None)
        try:
            with self.assertRaises(SyncError) as err:
                self.home.sign_in()
            self.assertIn("gh auth login", str(err.exception))
        finally:
            if saved:
                os.environ["G3XN_GITHUB_CLIENT_ID"] = saved

    def test_the_token_never_shows_in_the_status(self):
        self.home.use_token(self.github.token)
        self.assertNotIn(self.github.token, json.dumps(self.home.status()))


try:
    from test_daemon import get_json, request, start_daemon
except ImportError:                       # the app extra isn't installed
    start_daemon = None


@unittest.skipIf(start_daemon is None, "pip install g3xn[app] to test the daemon")
class GitHubRoutesTest(unittest.TestCase):
    def test_send_and_get_through_the_app(self):
        from g3xn.sim import VirtualPedal
        github = FakeGitHub()
        sync, libs = computer(github)
        libs["g3xn"].save(FRIDAY)
        url, stop = start_daemon(VirtualPedal(), gig_sync=sync)
        try:
            self.assertEqual(get_json(url + "/api/github")["signed_in"], False)
            code, body, _ = request(url + "/api/github", "PUT", {"token": "wrong"})
            self.assertEqual(code, 400)
            code, body, _ = request(url + "/api/github", "PUT", {"token": github.token})
            self.assertEqual((code, body["login"], body["repo"]), (200, "player", "player/g3xn-gigs"))
            code, body, _ = request(url + "/api/github/send", "POST")
            self.assertEqual((code, body["sent"]), (200, ["Friday"]))
            code, body, _ = request(url + "/api/github/get", "POST")
            self.assertEqual((code, body["unchanged"]), (200, 1))
            self.assertNotIn(github.token, json.dumps(get_json(url + "/api/github")))
        finally:
            stop()

    def test_off_for_a_virtual_pedal(self):
        from g3xn.sim import VirtualPedal
        url, stop = start_daemon(VirtualPedal())
        try:
            self.assertEqual(get_json(url + "/api/github"), {"available": False})
            code, body, _ = request(url + "/api/github/send", "POST")
            self.assertEqual(code, 400)
        finally:
            stop()


if __name__ == "__main__":
    unittest.main()
