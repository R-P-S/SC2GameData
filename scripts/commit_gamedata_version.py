#!/usr/bin/env python3
"""Commit one game's changed packages as a versioned Git commit and tag.

This script DOES NOT push. The workflow pushes only to R-P-S/SC2GameData.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

OWNER_REPO = "R-P-S/SC2GameData"
GAMES = {
    "sc2": {
        "product": "s2", "label": "SC2", "tag_prefix": "sc2",
        "build_file": "mods/core.sc2mod/base.sc2data/BuildId.txt",
    },
    "heroes": {
        "product": "hero", "label": "Heroes", "tag_prefix": "heroes",
        "build_file": "mods/core.stormmod/base.stormdata/BuildId.txt",
    },
}


def git(*args, capture=False):
    command = ["git", *args]
    if capture:
        return subprocess.check_output(command)
    subprocess.run(command, check=True)


def package_root(filename, game):
    parts = filename.replace("\\", "/").split("/")
    if not parts or parts[0] not in ("mods", "campaigns"):
        return None
    for index, part in enumerate(parts[1:], 1):
        part = part.lower()
        if part.endswith((".sc2mod", ".sc2campaign")):
            return "/".join(parts[:index + 1]) if game == "sc2" else None
        if part.endswith(".stormmod"):
            return "/".join(parts[:index + 1]) if game == "heroes" else None
    return None


def changed_packages(game):
    # Disabling rename detection ensures deletions/additions remain independently staged.
    data = git("-c", "status.renames=false", "status", "--porcelain=v1", "-z",
               "--untracked-files=all", "--", "mods", "campaigns", capture=True)
    roots = set()
    for line in data.split(b"\0"):
        if not line:
            continue
        if len(line) < 4 or line[2:3] != b" ":
            raise RuntimeError("Unexpected git status output: " + repr(line))
        root = package_root(os.fsdecode(line[3:]), game)
        if root:
            roots.add(root)
    return sorted(roots)


def resolve_version(product, build_id):
    """Resolve full version from Blizzard's US version table; safely fall back to build ID."""
    url = "http://us.patch.battle.net:1119/" + product + "/versions"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "R-P-S-SC2GameData-Versioner/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(1024 * 1024).decode("utf-8-sig")
        rows = [r.strip() for r in body.splitlines()
                if r.strip() and not r.lstrip().startswith("#")]
        if len(rows) < 2:
            raise ValueError("Missing version table header or records")
        headers = [p.split("!", 1)[0].strip().lower() for p in rows[0].split("|")]
        columns = {key: headers.index(key)
                   for key in ("region", "buildid", "versionsname")}
        for row in rows[1:]:
            values = row.split("|")
            if len(values) <= max(columns.values()):
                continue
            if values[columns["region"]].strip().lower() != "us":
                continue
            remote_build = values[columns["buildid"]].strip().removeprefix("B")
            version = values[columns["versionsname"]].strip()
            if remote_build != build_id[1:]:
                raise ValueError("CASC build " + build_id +
                                 " differs from patch server build " + remote_build)
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
                raise ValueError("Unexpected version name: " + repr(version))
            if not version.endswith("." + build_id[1:]):
                raise ValueError("Version name does not match CASC build: " + version)
            return version
        raise ValueError("US region not found")
    except (OSError, ValueError, IndexError) as error:
        print("WARNING: Cannot resolve full " + product + " version: " + str(error),
              file=sys.stderr)
        print("Using exact CASC build ID " + build_id + " as version.", file=sys.stderr)
        return build_id


def reject_existing_tag(tag):
    local = subprocess.run(["git", "show-ref", "--verify", "--quiet",
                            "refs/tags/" + tag], check=False)
    if local.returncode == 0:
        raise RuntimeError("Version tag already exists locally: " + tag)
    if local.returncode != 1:
        raise RuntimeError("Unable to check local tag " + tag)
    # Shallow Actions checkouts do not necessarily have older tags locally.
    # Check the authoritative fork to avoid accidentally reusing a tag.
    if os.getenv("GITHUB_ACTIONS") == "true":
        remote = subprocess.run(["git", "ls-remote", "--exit-code", "--tags",
                                 "origin", "refs/tags/" + tag],
                                stdout=subprocess.DEVNULL, check=False)
        if remote.returncode == 0:
            raise RuntimeError("Version tag already exists on the fork: " + tag)
        if remote.returncode != 2:
            raise RuntimeError("Unable to verify remote tag " + tag)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True, choices=GAMES)
    parser.add_argument("--build", required=True)
    parser.add_argument("--version", help="Verified historical Blizzard version name")
    parser.add_argument("--source-commit", help="Verified historical source snapshot SHA")
    parser.add_argument("--history-gap-from", help="Baseline build before uncovered historical gap")
    args = parser.parse_args()
    if os.getenv("GITHUB_REPOSITORY") != OWNER_REPO:
        raise RuntimeError("Refusing to commit outside " + OWNER_REPO)
    if not re.fullmatch(r"B[0-9]+", args.build):
        raise RuntimeError("Invalid CASC build ID: " + repr(args.build))

    game = GAMES[args.game]
    if Path(game["build_file"]).read_text(encoding="utf-8").strip() != args.build:
        raise RuntimeError("Extracted build ID does not match " + args.build)

    roots = changed_packages(args.game)
    if not roots:
        print("No changed " + game["label"] + " packages; no version commit needed.")
        return
    print("Staging " + str(len(roots)) + " changed " + game["label"] + " packages.")
    for index in range(0, len(roots), 50):
        git("add", "-A", "--", *roots[index:index + 50])
    if subprocess.run(["git", "diff", "--cached", "--quiet"],
                      check=False).returncode == 0:
        print("No staged " + game["label"] + " file changes.")
        return

    if args.version:
        if args.version != args.build and (
            not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", args.version)
            or not args.version.endswith("." + args.build[1:])
        ):
            raise RuntimeError("Invalid historical version name for " + args.build)
        version = args.version
    else:
        version = resolve_version(game["product"], args.build)
    tag = game["tag_prefix"] + "/v" + version
    reject_existing_tag(tag)

    message = game["label"] + ": Update to " + version
    if args.history_gap_from:
        if not re.fullmatch(r"B[0-9]+", args.history_gap_from):
            raise RuntimeError("Invalid history gap baseline")
        message += ("\\n\\nHistory incomplete: BlizzTrack's earliest available archive "
                    "is newer than repository baseline " + args.history_gap_from
                    + ". Intermediate older versions were not recovered.")
    if args.source_commit:
        if not re.fullmatch(r"[a-f0-9]{40}", args.source_commit, re.I):
            raise RuntimeError("Invalid archive source commit SHA")
        message += ("\n\nSource: jamiephan/HeroesOfTheStorm_Gamedata "
                    + args.source_commit)
    git("commit", "-m", message)
    git("tag", "-a", tag, "-m", game["label"] + " game data version " + version)
    print("Created " + game["label"] + " commit and tag " + tag)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
