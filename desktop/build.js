// Builds g3xn.exe (out/g3xn-win32-x64/), remembering this repo as the one whose daemon it starts.
const { packager } = require("@electron/packager");
const fs = require("node:fs");
const path = require("node:path");

const repo = path.resolve(__dirname, "..");
fs.writeFileSync(path.join(__dirname, "build-config.json"), JSON.stringify({ repo }, null, 2) + "\n");

packager({
  dir: __dirname,
  name: "g3xn",
  executableName: "g3xn",
  platform: "win32",
  arch: "x64",
  out: path.join(__dirname, "out"),
  overwrite: true,
  asar: true,
  ignore: [/^\/out($|\/)/, /^\/build\.js$/, /\.log$/],
  win32metadata: { CompanyName: "g3xn", FileDescription: "g3xn", ProductName: "g3xn" },
}).then(
  ([folder]) => console.log(`Built ${path.join(folder, "g3xn.exe")} (starts the daemon in ${repo})`),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
