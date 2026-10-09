#!/usr/bin/env python3
"""Recover SC2/Heroes releases missed between GitHub Actions runs.

Version history comes from BlizzTrack's archived Blizzard versions manifests.
CASC files still come directly from Blizzard via @jamiephan/casclib buildKey.
This program NEVER pushes. The workflow atomically pushes commits/tags to the fork.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FORK = "R-P-S/SC2GameData"
GAMES = {
    "sc2": ("s2", "mods/core.sc2mod/base.sc2data/BuildId.txt",
            "scripts/update_sc2_gamedata.js", "SC2"),
    "heroes": ("hero", "mods/core.stormmod/base.stormdata/BuildId.txt",
               "scripts/update_hots_gamedata.js", "HOTS"),
}
KEY = re.compile(r"^[a-fA-F0-9]{32}$")
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")


def json_get(url):
    request = Request(url, headers={
        "User-Agent": "R-P-S-SC2GameData-History/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} retrieving {url}")
        return json.loads(response.read(6_000_000))


def manifest_result(payload, where, *, paged=False):
    """Accept documented and common BlizzTrack JSON response envelopes.

    The documented payload uses a results object, but the live
    service has returned a different JSON shape. Inspect only validated
    arrays; never silently treat errors as empty history.
    """
    if isinstance(payload, dict):
        if payload.get("success") is False or payload.get("status") == "error":
            raise RuntimeError(
                f"BlizzTrack reported failure for {where}: "
                + json.dumps(payload, ensure_ascii=False)[:1000]
            )
        if payload.get("error") and not isinstance(payload.get("results"), (list, dict)):
            raise RuntimeError(
                f"BlizzTrack error for {where}: "
                + json.dumps(payload, ensure_ascii=False)[:1000]
            )

    # Handle nested or flat results/data arrays.
    candidates = [payload]
    seen = set()
    for candidate in candidates:
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        if isinstance(candidate, list):
            return {}, candidate
        if isinstance(candidate, dict):
            for key in ("results", "data", "items", "rows", "seqns", "result", "payload"):
                value = candidate.get(key)
                if isinstance(value, (list, dict)):
                    if isinstance(value, list):
                        return candidate, value
                    candidates.append(value)

    # Unknown response. Include a short public-data diagnostic in the
    # runner log, so the next failure can be fixed from evidence.
    preview = json.dumps(payload, ensure_ascii=False, default=str)[:1200]
    raise RuntimeError(
        f"Unexpected BlizzTrack response at {where}; "
        f"top-level type={type(payload).__name__}; "
        f"keys={list(payload)[:20] if isinstance(payload, dict) else 'n/a'}; "
        f"body={preview}"
    )


def fetch_history(product, max_scan):
    # Current BlizzTrack API routing and envelope, not the older ASP.NET
    # /api/manifest/seqn/<product>?filter=Versions layout.
    # API spec: https://blizztrack.com/swagger/doc.json
    base = "https://blizztrack.com/api/manifest/" + product
    seqns = []
    page_size = 25  # Maximum allowed by the documented API.
    page = 1
    while len(seqns) < max_scan:
        url = f"{base}/seqn?" + urlencode({
            "file": "versions", "page": page, "limit": page_size,
        })
        body, items = manifest_result(json_get(url), url, paged=True)
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError(f"Malformed archived sequence at {url}")
            try:
                seqn = int(item["seqn"])
            except (KeyError, ValueError, TypeError) as error:
                raise RuntimeError(f"Missing sequence number at {url}: {error}")
            seqns.append(seqn)
        if len(items) < page_size:
            break
        total_pages = body.get("total_pages")
        if total_pages is not None and page >= int(total_pages):
            break
        page += 1

    if not seqns:
        raise RuntimeError("BlizzTrack returned no version history for " + product)
    numbers = sorted(set(seqns), reverse=True)[:max_scan]

    print(f"BlizzTrack: found {len(numbers)} distinct archived sequence numbers "+
          f"for {product}.", flush=True)
    for number in numbers:
        url = f"{base}/versions?" + urlencode({"seqn": number})
        _, rows = manifest_result(json_get(url), url)
        us = [v for v in rows if isinstance(v, dict)
              and str(v.get("region", "")).lower() == "us"]
        if not us:
            continue
        row = us[0]
        try:
            build = "B" + str(int(row["build_id"]))
            key = str(row["build_config"]).strip().lower()
            version = str(row["version_name"]).strip()
        except (KeyError, ValueError, TypeError) as error:
            raise RuntimeError(f"Invalid archived version entry at {number}: {error}")
        if not KEY.fullmatch(key):
            raise RuntimeError(f"Missing or invalid build config for {build}")
        if version.upper().startswith("SC2."):
            version = version[4:]
        if not VERSION.fullmatch(version) or not version.endswith("." + build[1:]):
            # Never label a build with an unrelated or unverifiable version.
            version = build
        yield {"build": build, "key": key, "version": version, "seqn": number}


def probe_latest(game):
    """Ask online CASC for the ACTUAL latest version, not a tracking-service guess."""
    script = GAMES[game][2]
    cmd = ["node", script, "--probe"]
    result = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE)
    print(result.stdout, end="", flush=True)
    found = re.findall(r"^CASC_BUILD_ID=(B[0-9]+)$", result.stdout, re.MULTILINE)
    if len(found) != 1:
        raise RuntimeError("No verified latest CASC build ID from " + script)
    return found[0]


def candidates(game, current, online, scan_limit):
    product = GAMES[game][0]
    history = []
    seen = set()
    baseline_seen = current == online
    latest_seen = False

    for entry in fetch_history(product, scan_limit):
        build = entry["build"]
        if build in seen:
            continue
        seen.add(build)
        if build == online:
            latest_seen = True
        if build == current:
            baseline_seen = True
            break
        # Ignore regional archives ahead of Blizzard's currently served build.
        if int(build[1:]) <= int(online[1:]) and int(build[1:]) > int(current[1:]):
            history.append(entry)

    if not latest_seen and current != online:
        raise RuntimeError(f"BlizzTrack has not yet indexed current {product} build "
                           f"{online}. Not skipping possible intermediate patches.")
    if not baseline_seen:
        raise RuntimeError(
            f"Could not find installed {game} build {current} within {scan_limit} "
            "archived manifests. Refusing to skip unverified intermediate patches. "
            "Try a larger history_scan value or investigate BlizzTrack coverage."
        )
    history.reverse()
    if current != online and (not history or history[-1]["build"] != online):
        raise RuntimeError(f"No complete historical path from {current} to {online}.")
    return history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True, choices=GAMES)
    parser.add_argument("--max-builds", type=int, default=3,
                        help="Maximum intermediate builds to process this run")
    parser.add_argument("--history-scan", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if os.environ.get("GITHUB_REPOSITORY") != FORK:
        raise RuntimeError("Refusing to run outside " + FORK)
    if not (1 <= args.max_builds <= 10) or not (10 <= args.history_scan <= 1000):
        raise ValueError("max-builds must be 1..10; history-scan must be 10..1000")

    product, build_file, script, prefix = GAMES[args.game]
    start = Path(build_file).read_text(encoding="utf8").strip()
    if not re.fullmatch(r"B[0-9]+", start):
        raise RuntimeError(f"Invalid current {args.game} build in {build_file}: {start}")
    online = probe_latest(args.game)
    if int(online[1:]) < int(start[1:]):
        raise RuntimeError("Online build is older than repository build; refusing downgrade.")

    if start == online and not args.force:
        print(f"{args.game}: {start} is already current. Nothing to recover.")
        return

    if start != online:
        plans = candidates(args.game, start, online, args.history_scan)
    else:
        # Re-extract current version without tagging another historical release.
        plans = [{"build": start, "key": None, "version": start}]

    print(f"{args.game}: {len(plans)} available builds from {start} to {online}.")
    selected = plans[:args.max_builds]
    if len(plans) > len(selected):
        print(f"NOTICE: processing {len(selected)} of {len(plans)} missing builds "
              "this run; subsequent scheduled runs will continue.")

    for index, entry in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {args.game} {entry['build']} "
              f"({entry['version']}) build-config={entry['key']}", flush=True)
        env = os.environ.copy()
        env[f"{prefix}_BUILD_KEY"] = entry["key"] or ""
        env[f"{prefix}_EXPECTED_BUILD"] = entry["build"]
        env[f"{prefix}_FORCE"] = "true"
        env[f"{prefix}_DRY_RUN"] = "true" if args.dry_run else "false"
        # Each extraction stages and validates an entire build before replacing files.
        subprocess.run(["node", script], env=env, check=True)

        if not args.dry_run:
            subprocess.run([
                sys.executable, "scripts/commit_gamedata_version.py",
                "--game", args.game, "--build", entry["build"],
                "--version", entry["version"],
            ], check=True)
    print(f"{args.game}: history recovery pass finished successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HISTORY RECOVERY FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
