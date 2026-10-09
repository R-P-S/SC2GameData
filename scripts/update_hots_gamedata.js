#!/usr/bin/env node
"use strict";

// Refresh Heroes of the Storm text/code files from Blizzard's online CASC.
// This script does not run git or push to any GitHub repository.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Storage } = require("@jamiephan/casclib");

const ROOT = path.resolve(__dirname, "..");
const BUILD_FILE = "mods/core.stormmod/base.stormdata/BuildId.txt";
const MINIMUM_FILES = 1000;

function output(key, value) {
  if (process.env.GITHUB_OUTPUT) {
    fs.appendFileSync(process.env.GITHUB_OUTPUT, key + "=" + value + "\n");
  }
}

function eligible(name) {
  if (!/^mods\//i.test(name)) return false;
  const parts = name.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return false;
  // Never extract into, or delete, StarCraft II .sc2mod/.sc2campaign packages.
  if (!parts.some((part) => /\.stormmod$/i.test(part))) return false;
  if (parts.some((part) => /\.(?:sc2mod|sc2campaign)$/i.test(part))) return false;
  if (/\/editordata\/texturereduction(?:\/|$)/i.test(name)) return false;
  if (/(?:^|\/)(?:dede|eses|esmx|frfr|itit|kokr|plpl|ptbr|ruru|zhcn|zhtw)\.stormdata\//i.test(name)) return false;
  if (/(?:PreloadAssetDB|TextureReductionValues)\.txt$/i.test(name)) return false;

  // Source: original SC2Mapster/tools update.lua Heroes extraction patterns.
  return /\.(?:aitree|fx|xml|txt|json|galaxy|triggerlib|stormcomponents|stormcutscene|stormhotkeys|storminterface|stormlayout|stormlib|stormlocale|stormstyle)$/i.test(name)
    || /\/(?:DocumentInfo|Objects|Regions|Triggers)$/i.test(name);
}

// Preserve original Git filename capitalization on case-sensitive Linux runners.
const existingCase = new Map();
function collectTrackedNames(dir) {
  if (!fs.existsSync(dir)) return;
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, item.name);
    if (item.isDirectory()) collectTrackedNames(full);
    else if (item.isFile()) {
      const rel = path.relative(ROOT, full).split(path.sep).join("/");
      existingCase.set(rel.toLowerCase(), rel);
    }
  }
}
collectTrackedNames(path.join(ROOT, "mods"));

function normalizeName(fileName) {
  const parts = String(fileName).replace(/\\/g, "/").split("/");
  if (parts.length > 1) {
    parts[0] = parts[0].toLowerCase();
    for (let i = 1; i < parts.length; i++) {
      if (/\.stormmod$/i.test(parts[i])) parts[i] = parts[i].toLowerCase();
    }
  }
  const normalized = parts.join("/");
  if (normalized.toLowerCase() === BUILD_FILE.toLowerCase()) return BUILD_FILE;
  return existingCase.get(normalized.toLowerCase()) || normalized;
}

function pruneStormMods(dir) {
  if (!fs.existsSync(dir)) return;
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!item.isDirectory()) continue;
    const full = path.join(dir, item.name);
    if (/\.(?:sc2mod|sc2campaign)$/i.test(item.name)) continue;
    if (/\.stormmod$/i.test(item.name)) {
      fs.rmSync(full, { recursive: true, force: true });
    } else {
      pruneStormMods(full);
    }
  }
}

async function main() {
  if (process.env.GITHUB_REPOSITORY &&
      process.env.GITHUB_REPOSITORY !== "R-P-S/SC2GameData") {
    throw new Error("Refusing to run outside R-P-S/SC2GameData.");
  }

  const force = process.argv.includes("--force") || process.env.HOTS_FORCE === "true";
  const dryRun = process.argv.includes("--dry-run") || process.env.HOTS_DRY_RUN === "true";
  const installedBuild = fs.existsSync(path.join(ROOT, BUILD_FILE))
    ? fs.readFileSync(path.join(ROOT, BUILD_FILE), "utf8").trim() : "(missing)";
  const cache = path.join(process.env.RUNNER_TEMP || os.tmpdir(), "hots-casc-cache");

  console.log("Installed Heroes build: " + installedBuild);
  console.log("Opening Blizzard online CASC (hero, US)");
  const buildKey = process.env.HOTS_BUILD_KEY || "";
  const expectedBuild = process.env.HOTS_EXPECTED_BUILD || "";
  if (buildKey && !/^[0-9a-f]{32}$/i.test(buildKey)) {
    throw new Error("Invalid historical build configuration key");
  }
  // Probe current online build without modifying any checkout files.
  const storage = buildKey
    ? Storage.openEx(cache, {
        localPath: cache, codeName: "hero", region: "us",
        buildKey, online: true
      })
    : await Storage.openOnlineAsync(cache + "*hero*us");
  let staging = null;

  try {
    const onlineBuild = storage.readFile(BUILD_FILE).toString("utf8").trim();
    if (!/^B[0-9]+$/.test(onlineBuild)) {
      throw new Error("Invalid Heroes CASC build ID: " + onlineBuild);
    }
    console.log("Online Heroes build: " + onlineBuild);
    console.log("CASC_BUILD_ID=" + onlineBuild);
    if (expectedBuild && onlineBuild !== expectedBuild) {
      throw new Error("Historical build mismatch: expected " + expectedBuild + ", got " + onlineBuild);
    }
    if (process.argv.includes("--probe")) {
      output("updated", "false");
      return;
    }
    output("build_id", onlineBuild);

    if (installedBuild === onlineBuild && !force) {
      console.log("Heroes data already current. Nothing to extract.");
      output("updated", "false");
      return;
    }

    const files = [];
    const seen = new Set();
    for (const entry of storage.files("*")) {
      const name = normalizeName(entry.fileName);
      if (!eligible(name)) continue;
      const key = name.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      files.push(name);
    }
    files.sort();
    console.log("Matching Heroes files: " + files.length);
    if (files.length < MINIMUM_FILES) {
      throw new Error("Suspiciously small Heroes file list; refusing to update.");
    }

    for (const required of [
      BUILD_FILE.toLowerCase(),
      "mods/core.stormmod/base.stormdata/gamedata.xml",
      "mods/core.stormmod/base.stormdata/triggerlibs/nativelib.triggerlib"
    ]) {
      if (!seen.has(required)) {
        throw new Error("Required Heroes file missing from online listing: " + required);
      }
    }

    staging = fs.mkdtempSync(path.join(os.tmpdir(), "hots-gamedata-stage-"));
    for (let i = 0; i < files.length; i++) {
      const name = files[i];
      const target = path.resolve(staging, name);
      if (!target.startsWith(staging + path.sep)) {
        throw new Error("Unsafe Heroes CASC file path: " + name);
      }
      const content = storage.readFile(name);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, content);
      if ((i + 1) % 250 === 0 || i + 1 === files.length) {
        console.log("Extracted Heroes " + (i + 1) + "/" + files.length + " files");
      }
    }

    const stagedBuild = path.join(staging, BUILD_FILE);
    if (!fs.existsSync(stagedBuild) ||
        fs.readFileSync(stagedBuild, "utf8").trim() !== onlineBuild) {
      throw new Error("Staged Heroes BuildId.txt does not match online build.");
    }
    if (dryRun) {
      console.log("Heroes DRY RUN successful. Repository not changed.");
      output("updated", "false");
      return;
    }

    // Remove only .stormmod packages, never SC2 .sc2mod/.sc2campaign data.
    pruneStormMods(path.join(ROOT, "mods"));
    fs.cpSync(path.join(staging, "mods"), path.join(ROOT, "mods"), {
      recursive: true,
      force: true
    });
    console.log("Updated Heroes data to " + onlineBuild + "; SC2 files preserved.");
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
