// Builds the release: a zip holding g3xn.exe with the daemon frozen inside it, so it runs on a
// computer with no Python and no copy of this repo.
//
//     npm run release            out/release/g3xn-<version>-windows-x64.zip
//
// Needs, once: the repo's .venv with the app and mcp extras, PyInstaller in it
// (uv pip install --python .venv/Scripts/python.exe pyinstaller), and the app built (it is built here).
const { packager } = require("@electron/packager");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repo = path.resolve(__dirname, "..");
const out = path.join(__dirname, "out", "release");
const version = require("./package.json").version;
const python = path.join(repo, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const run = (cmd, args, cwd = repo) => execFileSync(cmd, args, { cwd, stdio: "inherit", shell: process.platform === "win32" && cmd === "npm" });

async function main() {
  if (process.platform !== "win32") throw new Error("the release build is Windows only for now");
  if (!fs.existsSync(python)) throw new Error(`No Python at ${python}: make the repo's .venv first`);
  fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });

  console.log("1/4 the app's screens");
  run("npm", ["run", "build"], path.join(repo, "app"));

  console.log("2/4 the daemon, frozen");
  const sep = ";";
  run(python, [
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "g3xn-daemon",
    "--distpath", path.join(out, "pyi-dist"), "--workpath", path.join(out, "pyi-work"), "--specpath", out,
    "--paths", repo,
    "--add-data", `${path.join(repo, "g3xn", "data")}${sep}g3xn/data`,
    "--add-data", `${path.join(repo, "app", "dist")}${sep}app/dist`,
    "--hidden-import", "mido.backends.rtmidi",
    "--collect-submodules", "mido", "--collect-submodules", "uvicorn", "--collect-submodules", "websockets",
    // not all of mcp: mcp.cli exits when typer is missing
    "--collect-submodules", "mcp.server", "--collect-submodules", "mcp.shared", "--collect-submodules", "mcp.client",
    "--collect-submodules", "g3xn",
    // push to talk (speech to text) is left out of the release: it is big, and the desk PC has no mic
    "--exclude-module", "numpy", "--exclude-module", "faster_whisper", "--exclude-module", "ctranslate2",
    "--exclude-module", "sounddevice", "--exclude-module", "onnxruntime", "--exclude-module", "av",
    "--exclude-module", "tokenizers", "--exclude-module", "huggingface_hub", "--exclude-module", "webview",
    "--exclude-module", "tkinter", "--exclude-module", "PyInstaller",
    path.join(__dirname, "daemon_entry.py"),
  ]);

  console.log("3/4 the window");
  // No build-config.json: a release must not carry the path of the computer that built it.
  const [folder] = await packager({
    dir: __dirname,
    name: "g3xn",
    executableName: "g3xn",
    appVersion: version,
    platform: "win32",
    arch: "x64",
    out,
    overwrite: true,
    asar: true,
    extraResource: [path.join(out, "pyi-dist", "g3xn-daemon")],
    ignore: [/^\/out($|\/)/, /^\/build\.js$/, /^\/release\.js$/, /^\/daemon_entry\.py$/, /^\/build-config\.json$/, /\.log$/],
    win32metadata: { CompanyName: "g3xn", FileDescription: "g3xn", ProductName: "g3xn" },
  });

  console.log("4/4 the zip");
  const zip = path.join(out, `g3xn-${version}-windows-x64.zip`);
  // Windows' own tar (bsdtar) makes zips. A Git Bash tar earlier on PATH can't.
  const tar = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "tar.exe");
  execFileSync(tar, ["-a", "-c", "-f", path.basename(zip), path.basename(folder)], { cwd: out, stdio: "inherit" });
  console.log(`Built ${zip}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
