#!/usr/bin/env node
"use strict";

// Update only SC2 text/code files from Blizzard's online CASC.
// This script does not run git or push to any GitHub repository.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Storage } = require("@jamiephan/casclib");

const ROOT = path.resolve(__dirname, "..");
const BUILD_FILE = "mods/core.sc2mod/base.sc2data/BuildId.txt";
const MINIMUM_FILES = 1000;

function output(key, value) {
  if (process.env.GITHUB_OUTPUT) {
    fs.appendFileSync(process.env.GITHUB_OUTPUT, key + "=" + value + "\n");
  }
}

function eligible(name) {
  if (!/^(mods|campaigns)\//i.test(name)) return false;
  const parts = name.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return false;
  if (!parts.some((part) => /\.(sc2mod|sc2campaign)$/i.test(part))) return false;
  if (/\/editordata\/texturereduction(?:\/|$)/i.test(name)) return false;
  if (/(?:^|\/)(?:dede|eses|esmx|frfr|itit|kokr|plpl|ptbr|ruru|zhcn|zhtw)\.sc2data\//i.test(name)) return false;
  if (/(?:PreloadAssetDB|TextureReductionValues)\.txt$/i.test(name)) return false;
  if (/(?:^|\/)nova\d+\.sc2map\//i.test(name)) return false;
  return /\.(?:fx|xml|txt|json|galaxy|sc2style|sc2hotkeys|sc2lib|triggerlib|sc2interface|sc2locale|sc2components|sc2layout|sc2cutscene|sc2scene)$/i.test(name)
    || /\/(?:DocumentInfo|Objects|Regions|Triggers)$/i.test(name);
}

function normalizeName(name) {
  const parts = String(name).replace(/\\/g, "/").split("/");
  if (parts.length > 1) {
    parts[0] = parts[0].toLowerCase();
    for (let i = 1; i < parts.length; i++) {
      if (/\.(sc2mod|sc2campaign)$/i.test(parts[i])) {
        parts[i] = parts[i].toLowerCase();
      }
    }
  }
  return parts.join("/");
}

function pruneSC2Directories(start) {
  if (!fs.existsSync(start)) return;
  for (const child of fs.readdirSync(start, { withFileTypes: true })) {
    if (!child.isDirectory()) continue;
    const full = path.join(start, child.name);
    if (/\.(sc2mod|sc2campaign)$/i.test(child.name)) {
      if (child.name.toLowerCase() === "novastoryassets.sc2mod") continue;
      fs.rmSync(full, { recursive: true, force: true });
    } else {
      pruneSC2Directories(full);
    }
  }
}

async function main() {
  if (process.env.GITHUB_REPOSITORY &&
      process.env.GITHUB_REPOSITORY !== "R-P-S/SC2GameData") {
    throw new Error("Refusing to run outside R-P-S/SC2GameData.");
  }

  const force = process.argv.includes("--force") || process.env.SC2_FORCE === "true";
  const dryRun = process.argv.includes("--dry-run") || process.env.SC2_DRY_RUN === "true";
  const installedBuild = fs.existsSync(path.join(ROOT, BUILD_FILE))
    ? fs.readFileSync(path.join(ROOT, BUILD_FILE), "utf8").trim() : "(missing)";
  const cache = path.join(process.env.RUNNER_TEMP || os.tmpdir(), "sc2-casc-cache");

  console.log("Installed build: " + installedBuild);
  console.log("Opening Blizzard online CASC (s2, US)");
  const storage = await Storage.openOnlineAsync(cache + "*s2*us");
  let staging = null;

  try {
    const latestBuild = storage.readFile(BUILD_FILE).toString("utf8").trim();
    if (!/^B[0-9]+$/.test(latestBuild)) {
      throw new Error("Invalid CASC build ID: " + latestBuild);
    }
    console.log("Online build: " + latestBuild);
    output("build_id", latestBuild);

    if (installedBuild === latestBuild && !force) {
      console.log("Already current. Nothing to update.");
      output("updated", "false");
      return;
    }

    const files = [];
    const seen = new Set();
    for (const entry of storage.files("*")) {
      const name = normalizeName(entry.fileName);
      if (!eligible(name)) continue;
      const lower = name.toLowerCase();
      if (seen.has(lower)) continue;
      seen.add(lower);
      files.push(name);
    }
    files.sort();
    console.log("Matching SC2 files: " + files.length);

    if (files.length < MINIMUM_FILES) {
      throw new Error("Suspiciously small CASC file listing; refusing to update.");
    }
    for (const required of [
      BUILD_FILE.toLowerCase(),
      "mods/core.sc2mod/base.sc2data/triggerlibs/nativelib.triggerlib",
      "mods/core.sc2mod/base.sc2data/gamedata.xml"
    ]) {
      if (!seen.has(required)) {
        throw new Error("Required SC2 file missing from listing: " + required);
      }
    }

    staging = fs.mkdtempSync(path.join(os.tmpdir(), "sc2gamedata-stage-"));
    for (let i = 0; i < files.length; i++) {
      const name = files[i];
      const target = path.resolve(staging, name);
      if (!target.startsWith(staging + path.sep)) {
        throw new Error("Unsafe file path: " + name);
      }
      const content = storage.readFile(name);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, content);
      if ((i + 1) % 250 === 0 || i + 1 === files.length) {
        console.log("Extracted " + (i + 1) + "/" + files.length);
      }
    }

    const stagedBuild = path.join(staging, BUILD_FILE);
    if (!fs.existsSync(stagedBuild) ||
        fs.readFileSync(stagedBuild, "utf8").trim() !== latestBuild) {
      throw new Error("Staged BuildId.txt does not match the online build.");
    }
    if (dryRun) {
      console.log("DRY RUN successful. No repository files changed.");
      output("updated", "false");
      return;
    }

    for (const subdir of ["mods", "campaigns"]) {
      pruneSC2Directories(path.join(ROOT, subdir));
      const source = path.join(staging, subdir);
      if (fs.existsSync(source)) {
        fs.cpSync(source, path.join(ROOT, subdir), {
          recursive: true,
          force: true
        });
      }
    }
    console.log("Updated SC2 snapshot to " + latestBuild + "; HOTS mods preserved.");
    output("updated", "true");
  } finally {
    storage.close();
    if (staging) fs.rmSync(staging, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exitCode = 1;
});
