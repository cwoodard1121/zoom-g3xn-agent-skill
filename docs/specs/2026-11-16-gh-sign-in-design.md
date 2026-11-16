# Sign in with GitHub through the GitHub CLI (#7)

## Goal

"Sign in with GitHub" in the Gigs view works for any user without g3xn having its own GitHub app.

## Facts

The owner said "im not registering an app on github" and "do it thru gh cli". Without a terminal, `gh auth login --web` prints a one-time code and https://github.com/login/device, then waits until the user says yes there (checked with gh 2.95.0 in an empty config folder). `gh auth token` then gives the token, which g3xn already uses.

## Decisions

| Question | Options | Choice |
|---|---|---|
| How does the app sign in? | its own OAuth app (device flow) / the GitHub CLI's login | The GitHub CLI's login. The device flow and its client id go |
| Who opens the page? | the user / the app | The daemon opens it in the browser, and the app shows the code and the link too |
| No GitHub CLI? | refuse / paste a token | Paste a token, with a link to cli.github.com |

## Design

`GigSync.sign_in()` starts `gh auth login --hostname github.com --git-protocol https --web --scopes repo` with no window and no input, reads its output until the code and the page appear (30 s at most), opens the page, and returns them. A thread waits for the CLI to end. Then `status()` reads the CLI's token as before. A second click while it waits returns the same code. If it ends without a sign-in, `status()["problem"]` says why. Closing the app stops a waiting sign-in.

## Surfaces

The Gigs view's On GitHub panel. `POST /api/github/sign-in` (phone refused, as before).

## Data and interfaces

`GET /api/github` adds `gh_page`. `can_sign_in` now means the GitHub CLI is installed. No new route.

## Edge cases

A pasted token GitHub now refuses: the code still shows, a finished CLI login drops that token, and the panel offers Forget the saved token and Paste a token instead. The CLI is started without colour and without `--git-protocol`, so its code is readable and the user's git protocol stays. A CLI installed while g3xn runs is found in its install folders. No CLI: the panel shows the token box and a link to cli.github.com. A CLI that prints no code: it is stopped and its words are in the error. The code runs out after 15 minutes: the problem line says so, and the button starts again.

## Out of scope

Signing out of the GitHub CLI (that is `gh auth logout`, the user's own).

## Success check

On a computer with the GitHub CLI but no login, press Sign in with GitHub, type the code, and the panel shows Send my gigs.
