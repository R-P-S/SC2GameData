#!/usr/bin/env python3
"""Extract an exact archived Heroes snapshot from jamiephan's versioned Git history.

Use only for historical builds that were independently listed in VERSIONS.md.
No writes outside Heroes .stormmod packages; no Git pushes.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

FORK = "R-P-S/SC2GameData"
ARCHIVE = "https://github.com/jamiephan/HeroesOfTheStorm_Gamedata.git"
REPO = Path(__file__).resolve().parent.parent
BUILD_FILE = "mods/core.stormmod/base.stormdata/BuildId.txt"
# Archived release 2.52.2.82624 removed both build-ID files upstream.
# This exact commit is independently documented in VERSIONS.md.
# Only its missing tracking BuildId.txt may be reconstructed; no game data is invented.
MISSING_BUILDID_EXCEPTION = {
    "B82624": "2d12ec29787fed3c545ebeeea4fdaeff310618f1",
}
ALLOWED = re.compile(
    r"\.(aitree|fx|xml|txt|json|galaxy|triggerlib|stormcomponents|"
    r"stormcutscene|stormhotkeys|storminterface|stormlayout|stormlib|"
    r"stormlocale|stormstyle)$", re.I,
)
SPECIAL = re.compile(r"/(DocumentInfo|Objects|Regions|Triggers)$", re.I)
REGIONAL = re.compile(
    r"/(dede|eses|esmx|frfr|itit|kokr|plpl|ptbr|ruru|zhcn|zhtw)"
    r"\.stormdata/", re.I,
)


def run(*command, cwd=None, capture=False):
    if capture:
        return subprocess.check_output(command, cwd=cwd, text=True).strip()
    subprocess.run(command, check=True, cwd=cwd)


def collect_case():
    mapping = {}
    for folder, _, files in os.walk(REPO / "mods"):
        for filename in files:
            local = (Path(folder) / filename).relative_to(REPO).as_posix()
            mapping[local.lower()] = local
    return mapping


def eligible(rel):
    parts = rel.replace("\\", "/").split("/")
    if not parts or parts[0].lower() != "mods":
        return False
    if any(part in ("", ".", "..") for part in parts):
        return False
    if not any(part.lower().endswith(".stormmod") for part in parts[1:-1]):
        return False
    if any(part.lower().endswith((".sc2mod", ".sc2campaign")) for part in parts):
        return False
    if REGIONAL.search(rel):
        return False
    if "/editordata/texturereduction/" in rel.lower():
        return False
    if re.search(r"(PreloadAssetDB|TextureReductionValues)\.txt$", rel, re.I):
        return False
    return bool(ALLOWED.search(rel) or SPECIAL.search(rel))


def normalized_name(name, case):
    parts = name.split("/")
    parts[0] = parts[0].lower()
    parts[1:] = [p.lower() if p.lower().endswith(".stormmod") else p
                 for p in parts[1:]]
    normalized = "/".join(parts)
    if normalized.lower() == BUILD_FILE.lower():
        return BUILD_FILE
    return case.get(normalized.lower(), normalized)


def remove_stormmods(base):
    if not base.exists():
        return
    for folder, dirs, _ in os.walk(base, topdown=True):
        remaining = []
        for name in dirs:
            full = Path(folder) / name
            if name.lower().endswith(".stormmod"):
                shutil.rmtree(full)
            else:
                remaining.append(name)
        dirs[:] = remaining


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if os.getenv("GITHUB_REPOSITORY") != FORK:
        raise RuntimeError("Refusing to run outside " + FORK)
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit, re.I):
        raise ValueError("Unverified archive commit SHA")
    if not re.fullmatch(r"B[0-9]+", args.build):
        raise ValueError("Invalid expected build ID")

    cache = Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir())) / "heroes-archive-git"
    if not (cache / ".git").exists():
        cache.mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", str(cache))
        run("git", "-C", str(cache), "remote", "add", "source", ARCHIVE)
    # A partial/shallow fetch avoids downloading decades of Git history.
    # The archive ref is pinned to the exact SHA in VERSIONS.md.
    print(f"Fetching jamiephan Heroes archive commit {args.commit}", flush=True)
    run("git", "-C", str(cache), "fetch", "--no-tags", "--depth=1",
        "--filter=blob:none", "source", args.commit)
    sha = run("git", "-C", str(cache), "rev-parse", "FETCH_HEAD", capture=True)
    if sha.lower() != args.commit.lower():
        raise RuntimeError("Fetched archive commit SHA mismatch")
    run("git", "-C", str(cache), "checkout", "-q", "-f", "--detach", "FETCH_HEAD")

    src_mods = cache / "mods"
    if not src_mods.is_dir():
        raise RuntimeError("Archived commit has no mods folder")
    casing = collect_case()
    files = {}
    for folder, dirs, names in os.walk(src_mods):
        dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
        for name in names:
            src = Path(folder) / name
            if src.is_symlink() or not src.is_file():
                continue
            rel = src.relative_to(cache).as_posix()
            if not eligible(rel):
                continue
            target_name = normalized_name(rel, casing)
            key = target_name.lower()
            if key in files:
                raise RuntimeError("Case-insensitive filename collision: " + rel)
            files[key] = (src, target_name)

    if len(files) < 1000:
        raise RuntimeError(f"Archived snapshot has only {len(files)} eligible files")
    required = (
        "mods/core.stormmod/base.stormdata/gamedata.xml",
        "mods/core.stormmod/base.stormdata/triggerlibs/nativelib.galaxy",
    )
    for name in required:
        if name not in files:
            raise RuntimeError("Archived snapshot missing required file: " + name)

    missing_build_id = BUILD_FILE.lower() not in files
    if missing_build_id:
        if MISSING_BUILDID_EXCEPTION.get(args.build) != args.commit.lower():
            raise RuntimeError(
                "Archived snapshot missing required file: " + BUILD_FILE
            )
        print(
            "WARNING: Archived B82624 commit omits BuildId.txt. "
            "Using the verified version-to-commit mapping to reconstruct "
            "only this tracking marker; original archived game data remains unchanged.",
            flush=True,
        )
    else:
        source_build = files[BUILD_FILE.lower()][0].read_text(encoding="utf-8-sig").strip()
        if source_build != args.build:
            raise RuntimeError(
                f"Archived build-ID mismatch: expected {args.build}, got {source_build}"
            )

    with tempfile.TemporaryDirectory(prefix="heroes-archive-stage-") as stage:
        stage_path = Path(stage)
        for i, (src, target_name) in enumerate(files.values(), 1):
            dst = stage_path / target_name
            if stage_path.resolve() not in dst.resolve().parents:
                raise RuntimeError("Unsafe archive path: " + target_name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            if i % 1000 == 0:
                print(f"Staged {i}/{len(files)} Heroes files", flush=True)

        if missing_build_id:
            # Version marker only: the archived commit is source-pinned above.
            marker = stage_path / BUILD_FILE
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(args.build + "\n", encoding="utf-8")

        if args.dry_run:
            print(
                f"Heroes archive DRY RUN succeeded: {args.build}, "
                f"{len(files)} verified files, no working tree changes.",
                flush=True,
            )
            return

        remove_stormmods(REPO / "mods")
        shutil.copytree(stage_path / "mods", REPO / "mods", dirs_exist_ok=True)
        if (REPO / BUILD_FILE).read_text(encoding="utf-8").strip() != args.build:
            raise RuntimeError("Final archived build ID verification failed")
        print(
            f"Recovered Heroes {args.build} from jamiephan archival commit "
            f"{args.commit}; {len(files)} text/code files installed.",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"HEROES ARCHIVE EXTRACTION FAILED: {error}", file=sys.stderr)
        sys.exit(1)
