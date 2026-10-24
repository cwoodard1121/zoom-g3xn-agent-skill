// The g3xn app in its own window. It finds the g3xn daemon that's already running, or starts one
// with the phone remote on (pair a phone from the app's Phone sheet), and stops the daemon again on
// quit if it started it.
//
//     npm start            the real pedal
//     npm run sim          a virtual pedal, nothing plugged in (its own ports, nothing saved)
//     npm run build        g3xn.exe in out/g3xn-win32-x64/
//
// The daemon is the repo's own (.venv/Scripts/g3xn-daemon.exe): the repo is G3XN_REPO, else the
// one this was built from (build-config.json), else the folder above this one.
const { app, BrowserWindow, session, shell } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const SIM = process.argv.includes("--sim");
const HOME = path.join(os.homedir(), ".g3xn");
const LOG = path.join(HOME, SIM ? "desktop-sim.log" : "desktop.log");
const NIGHT = "#050403";

function repo() {
  if (process.env.G3XN_REPO) return process.env.G3XN_REPO;
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, "build-config.json"), "utf8")).repo;
  } catch {
    return path.resolve(__dirname, "..");
  }
}

async function answers(url) {
  try {
    const r = await fetch(url + "/api/status", { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch {
    return false;
  }
}

/** The daemon already running (it says where in ~/.g3xn/daemon.json), if it really answers. */
async function runningDaemon() {
  try {
    const { url } = JSON.parse(fs.readFileSync(path.join(HOME, "daemon.json"), "utf8"));
    return (await answers(url)) ? url : null;
  } catch {
    return null;
  }
}

const freePort = () =>
  new Promise((resolve, reject) => {
    const s = net.createServer();
    s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });

let daemon = null; // the daemon this window started, if it did

async function startDaemon() {
  const exe = path.join(repo(), ".venv", "Scripts", process.platform === "win32" ? "g3xn-daemon.exe" : "g3xn-daemon");
  if (!fs.existsSync(exe)) throw new Error(`No g3xn daemon at ${exe}. Set G3XN_REPO to the g3xn folder.`);
  let port = 8370;
  const args = ["--remote"];
  if (SIM) {
    port = await freePort();
    args.push("--sim", "--port", String(port), "--remote-port", String(await freePort()));
  }
  fs.mkdirSync(HOME, { recursive: true });
  const log = fs.openSync(LOG, "a");
  fs.writeSync(log, `\n--- ${new Date().toISOString()} g3xn-daemon ${args.join(" ")}\n`);
  daemon = spawn(exe, args, { cwd: repo(), windowsHide: true, stdio: ["ignore", log, log] });
  daemon.on("exit", () => (daemon = null));
  const url = `http://127.0.0.1:${port}`;
  for (let waited = 0; waited < 30000; waited += 250) {
    if (await answers(url)) return url;
    if (!daemon) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`The g3xn daemon didn't start. What it said is in ${LOG}`);
}

/** Stop the daemon this window started, and what it started (tailscale serve) with it. */
function stopDaemon() {
  if (!daemon) return;
  const pid = daemon.pid;
  daemon = null;
  if (process.platform === "win32") execFile("taskkill", ["/PID", String(pid), "/T", "/F"], () => {});
  else process.kill(pid);
}

// --- the window ---

const boundsFile = () => path.join(app.getPath("userData"), "window.json");
function savedBounds() {
  try {
    return JSON.parse(fs.readFileSync(boundsFile(), "utf8"));
  } catch {
    return { width: 1440, height: 960 };
  }
}

const page = (title, body) =>
  "data:text/html;charset=utf-8," +
  encodeURIComponent(`<!doctype html><title>g3xn</title><style>
    html,body{margin:0;height:100%;background:${NIGHT};color:#ffb000;font:15px/1.5 system-ui,sans-serif}
    body{display:grid;place-items:center;text-align:center}
    h1{font:400 13px/1 sans-serif;letter-spacing:.4em;text-transform:uppercase;color:#b07a00;margin:0 0 18px}
    p{margin:0;font-size:22px;text-shadow:0 0 12px rgba(255,176,0,.55)}
    small{display:block;margin-top:14px;color:#b07a00;font-size:13px;max-width:60ch}
    i{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ffb000;box-shadow:0 0 10px #ffb000;margin-right:10px;animation:b 1s steps(2) infinite}
    @keyframes b{50%{opacity:.25}}</style>
    <div><h1>G3XN</h1><p>${title}</p>${body ? `<small>${body}</small>` : ""}</div>`);

async function open() {
  const win = new BrowserWindow({
    ...savedBounds(),
    minWidth: 380,
    minHeight: 560,
    title: "g3xn",
    backgroundColor: NIGHT,
    autoHideMenuBar: true,
    show: false,
    webPreferences: { autoplayPolicy: "no-user-gesture-required", spellcheck: false },
  });
  win.once("ready-to-show", () => win.show());
  const keep = () => {
    if (!win.isMaximized() && !win.isMinimized()) fs.writeFileSync(boundsFile(), JSON.stringify(win.getBounds()));
  };
  win.on("resized", keep);
  win.on("moved", keep);
  // YouTube, Spotify and other links open in the browser, not in another app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });

  win.loadURL(page(`<i></i>${SIM ? "Starting a virtual pedal…" : "Finding the pedal…"}`));
  let url;
  try {
    url = (!SIM && (await runningDaemon())) || (await startDaemon());
    if (!daemon) {
      // Someone else's daemon (g3xn-daemon in a terminal): turn its phone remote on too.
      await fetch(url + "/api/remote", { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"on":true}' }).catch(() => {});
    }
  } catch (err) {
    win.loadURL(page("g3xn couldn't start", String(err.message || err)));
    return;
  }

  // The microphone (talking, the scope) and full screen, for the app's own pages only.
  const ours = (u) => typeof u === "string" && u.startsWith(url);
  session.defaultSession.setPermissionRequestHandler((wc, permission, done) =>
    done(["media", "fullscreen", "clipboard-sanitized-write"].includes(permission) && ours(wc.getURL())));
  session.defaultSession.setPermissionCheckHandler((wc, permission, origin) => ["media", "fullscreen"].includes(permission) && ours(origin + "/"));
  win.webContents.on("will-navigate", (e, to) => {
    if (!ours(to)) {
      e.preventDefault();
      if (/^https?:/.test(to)) shell.openExternal(to);
    }
  });
  win.loadURL(url + "/#stage");
}

// The sim keeps its own window size and runs beside the real one.
if (SIM) app.setPath("userData", path.join(app.getPath("userData"), "sim"));
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
  app.whenReady().then(open);
  app.on("window-all-closed", () => app.quit());
  app.on("will-quit", stopDaemon);
}
