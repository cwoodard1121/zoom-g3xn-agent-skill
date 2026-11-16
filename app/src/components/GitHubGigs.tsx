// Gigs on GitHub: send this computer's gigs to the user's own private repo, and get them on
// another computer or pedalboard. Signing in: GitHub's code page, a pasted token, or the
// GitHub CLI's own login.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { GitHubStatus, SyncResult } from "../api";
import { usePedal } from "../pedal";

function summary(r: SyncResult): string {
  const moved = r.action === "send" ? r.sent ?? [] : r.got ?? [];
  const parts = [
    moved.length ? `${r.action === "send" ? "Sent" : "Got"} ${moved.length} gig${moved.length === 1 ? "" : "s"}` : "",
    r.deleted.length ? `deleted ${r.deleted.length}` : "",
    r.unchanged ? `${r.unchanged} already the same` : "",
  ].filter(Boolean);
  return (parts.join(", ") || "Nothing to move") + ` (${r.repo})`;
}

export function GitHubGigs() {
  const { act } = usePedal();
  const [gh, setGh] = useState<GitHubStatus | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<"send" | "get" | null>(null);

  const load = useCallback(() => api.github().then(setGh, () => setGh(null)), []);
  useEffect(() => {
    load();
  }, [load]);
  // While GitHub waits for the code to be typed in, look again every two seconds.
  useEffect(() => {
    if (!gh?.signing_in) return;
    const id = window.setInterval(load, 2000);
    return () => window.clearInterval(id);
  }, [gh?.signing_in, load]);

  if (!gh || !gh.available) return null;

  const move = async (what: "send" | "get") => {
    setBusy(what);
    const r = await act(() => (what === "send" ? api.githubSend() : api.githubGet()), summary);
    setBusy(null);
    if (r) load();
  };

  return (
    <div className="github-gigs">
      <h2 className="github-title">On GitHub</h2>
      {gh.signed_in ? (
        <>
          <p className="github-note">
            {gh.login} · <a href={`https://github.com/${gh.repo}`} target="_blank" rel="noreferrer">{gh.repo}</a>
          </p>
          <div className="github-actions">
            <button className="button" disabled={!!busy} onClick={() => move("send")}>
              {busy === "send" ? "Sending…" : "Send my gigs"}
            </button>
            <button className="button" disabled={!!busy} onClick={() => move("get")}>
              {busy === "get" ? "Getting…" : "Get gigs"}
            </button>
          </div>
          {gh.last && <p className="github-note">Last: {summary(gh.last)}</p>}
          {gh.via === "app" && (
            <button className="link-button" onClick={() => act(() => api.githubSignOut()).then((s) => s && setGh({ ...s, available: true }))}>
              Sign out
            </button>
          )}
        </>
      ) : gh.signing_in ? (
        <p className="github-note">
          Type <b className="github-code">{gh.signing_in.code}</b> at{" "}
          <a href={gh.signing_in.url} target="_blank" rel="noreferrer">{gh.signing_in.url.replace("https://", "")}</a>
        </p>
      ) : (
        <>
          <p className="github-note">Keep your gigs in your own GitHub and get them on another computer.</p>
          {gh.can_sign_in ? (
            <button className="button primary" onClick={() => act(() => api.githubSignIn()).then(load)}>Sign in with GitHub</button>
          ) : (
            <form
              className="github-token"
              onSubmit={async (e) => {
                e.preventDefault();
                const s = await act(() => api.githubToken(token.trim()), (s) => `Signed in as ${s.login}`);
                if (s) {
                  setGh({ ...s, available: true });
                  setToken("");
                }
              }}
            >
              <input
                type="password"
                placeholder="Paste a GitHub token"
                aria-label="GitHub token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <button className="button" type="submit" disabled={!token.trim()}>Sign in</button>
              <a className="github-note" href={gh.token_page} target="_blank" rel="noreferrer">Make a token (tick “repo”)</a>
            </form>
          )}
          {gh.problem && <p className="github-note error">{gh.problem}</p>}
        </>
      )}
    </div>
  );
}
