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
    seen_seqns = set()
    page_size = 25  # Requested size; server may enforce a smaller default.
    page = 1
    # One archived sequence can contain multiple regional builds. Never
    # interpret a short result page as the end of the archive.
    while len(seqns) < max_scan:
        url = f"{base}/seqn?" + urlencode({
            "file": "versions", "page": page, "limit": page_size,
        })
        body, items = manifest_result(json_get(url), url, paged=True)
        total_pages = body.get("total_pages")
        total = body.get("total")
        actual_page = body.get("page")
        print(f"BlizzTrack seqn page {page}: {len(items)} entries, "
              f"reported page={actual_page}, total_pages={total_pages}, "
              f"total={total}", flush=True)

        if actual_page is not None and int(actual_page) != page:
            raise RuntimeError(
                f"BlizzTrack ignored page={page} and returned page={actual_page}; "
                "refusing to silently truncate historical builds."
            )
        if not items:
            if total_pages is not None and page <= int(total_pages):
                raise RuntimeError(
                    f"Unexpected empty BlizzTrack history page {page} "
                    f"before advertised final page {total_pages}"
                )
            break

        before = len(seen_seqns)
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError(f"Malformed archived sequence at {url}")
            try:
                seqn = int(item["seqn"])
            except (KeyError, ValueError, TypeError) as error:
                raise RuntimeError(f"Missing sequence number at {url}: {error}")
            if seqn not in seen_seqns:
                seen_seqns.add(seqn)
                seqns.append(seqn)
        if len(seen_seqns) == before:
            raise RuntimeError(
                f"BlizzTrack returned no new sequence numbers on page {page}; "
                "pagination may be broken."
            )
        if total_pages is not None and page >= int(total_pages):
            if total is not None and len(seen_seqns) < int(total):
                print(
                    f"WARNING: BlizzTrack reports {total} snapshots but "
                    f"advertises only {total_pages} pages, yielding "
                    f"{len(seen_seqns)} records; archive may be incomplete.",
                    flush=True,
                )
            break
        elif len(items) < int(body.get("per_page", page_size)):
            # Use response's declared page size when available. When the
            # server omits it, do NOT assume 10 results means no more pages.
            # Continue until an empty page, limited below.
            if body.get("per_page") is not None:
                break
        page += 1
        if page > max_scan + 1:
            raise RuntimeError("BlizzTrack pagination exceeded safety limit.")


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


def heroes_archival_versions(current, online):
    """Pinned commits from jamiephan's documented Heroes VERSIONS.md."""
    url = ("https://raw.githubusercontent.com/jamiephan/"
           "HeroesOfTheStorm_Gamedata/master/VERSIONS.md")
    request = Request(url, headers={"User-Agent": "R-P-S-SC2GameData-History/1.0"})
    with urlopen(request, timeout=35) as response:
        body = response.read(1500000).decode("utf8")
    pattern = re.compile(
        r"(?m)^- ([0-9]+(?:\.[0-9]+)+): .*?"
        r"https://github\.com/jamiephan/HeroesOfTheStorm_Gamedata/"
        r"commit/([0-9a-f]{40})"
    )
    found = {}
    for version, sha in pattern.findall(body):
        build = "B" + version.split(".")[-1]
        found[build] = {
            "build": build, "version": version, "archive_commit": sha,
            "key": None, "source": "jamiephan-git",
        }
    if current not in found:
        raise RuntimeError("Jamie's version list does not contain baseline " + current)
    if online not in found:
        raise RuntimeError("Jamie's version list does not contain current " + online)
    plan = [
        found[b] for b in sorted(found, key=lambda x: int(x[1:]))
        if int(current[1:]) < int(b[1:]) <= int(online[1:])
    ]
    print(f"Heroes Git archive: {len(found)} documented version snapshots; "
          f"{len(plan)} patches between {current} and {online}.", flush=True)
    return plan


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


def candidates(game, current, online, scan_limit, allow_gap=False):
    """Return chronological recoverable builds and an optional archive coverage gap.

    A matching baseline snapshot is NOT required if the archive contains
    builds older than the baseline. When the oldest archived build is newer,
    allow an explicitly opted-in best-effort recovery, while preserving the
    missing coverage in the very first recovered commit message.
    """
    product = GAMES[game][0]
    history_by_build = {}
    for entry in fetch_history(product, scan_limit):
        history_by_build.setdefault(entry["build"], entry)
    if not history_by_build:
        raise RuntimeError(f"No archived {game} builds could be identified.")

    lower = int(current[1:])
    upper = int(online[1:])
    recorded = sorted(int(b[1:]) for b in history_by_build)
    oldest, newest = recorded[0], recorded[-1]
    print(
        f"{game}: archive coverage B{oldest}..B{newest}, "
        f"repository {current}, Blizzard {online} "
        f"({len(recorded)} unique recorded builds).",
        flush=True,
    )

    if online not in history_by_build and current != online:
        raise RuntimeError(
            f"BlizzTrack has not yet indexed current {product} build {online}; "
            "refusing to label an incomplete patch sequence as up to date."
        )

    missing_start = oldest > lower
    if missing_start and not allow_gap:
        raise RuntimeError(
            f"Historical archive starts at B{oldest}, after installed {current}. "
            f"Builds between {current} and B{oldest} are not recoverable from "
            "the available BlizzTrack records. To recover only the available "
            "patches, rerun manually with 'Allow incomplete archive history' "
            "checked; the gap will be recorded in the first commit."
        )

    if current not in history_by_build and oldest <= lower:
        print(
            f"NOTE: exact baseline {current} was not indexed, but history "
            f"extends back to B{oldest}, before the baseline. "
            "Recovering known intervening builds.",
            flush=True,
        )

    gap = current if missing_start else None
    plan = [
        history_by_build["B" + str(value)]
        for value in recorded if lower < value <= upper
    ]
    if not plan or plan[-1]["build"] != online:
        raise RuntimeError(
            f"No verified path from {current} to current online build {online}."
        )
    if gap:
        print(
            f"WARNING: incomplete historical coverage. Known archive starts "
            f"at B{oldest}, newer than {current}. Earlier missing versions "
            "cannot be reconstructed from this source.",
            flush=True,
        )
    return plan, gap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True, choices=GAMES)
    parser.add_argument("--max-builds", type=int, default=3,
                        help="Maximum intermediate builds to process this run")
    parser.add_argument("--history-scan", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-gap", action="store_true",
                        help="Allow explicitly documented incomplete history")
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

    if start == online:
        print(f"{args.game}: {start} is already current. No historical backlog.")
        if args.game == "heroes" and os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as output:
                output.write("caught_up=true\n")
        return

    if start != online:
        if args.game == "heroes":
            plans = heroes_archival_versions(start, online)
            gap = None
        else:
            plans, gap = candidates(args.game, start, online, args.history_scan,
                                    allow_gap=args.allow_gap)
    else:
        # Re-extract current version without tagging another historical release.
        plans = [{"build": start, "key": None, "version": start}]
        gap = None

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
        if args.game == "heroes" and entry.get("archive_commit"):
            command = [
                sys.executable, "scripts/extract_hots_archive.py",
                "--commit", entry["archive_commit"], "--build", entry["build"],
            ]
            if args.dry_run:
                command.append("--dry-run")
            subprocess.run(command, env=env, check=True)
        else:
            subprocess.run(["node", script], env=env, check=True)

        if not args.dry_run:
            command = [
                sys.executable, "scripts/commit_gamedata_version.py",
                "--game", args.game, "--build", entry["build"],
                "--version", entry["version"],
            ]
            if entry.get("archive_commit"):
                command += ["--source-commit", entry["archive_commit"]]
            if gap and index == 1:
                command += ["--history-gap-from", gap]
            subprocess.run(command, check=True)
    completed = bool(selected and selected[-1]["build"] == online)
    if args.game == "heroes":
        print(f"Heroes historical backlog complete: {completed}", flush=True)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as output:
                output.write(f"caught_up={str(completed).lower()}\n")
    print(f"{args.game}: history recovery pass finished successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HISTORY RECOVERY FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
