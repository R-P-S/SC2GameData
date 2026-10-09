# Automated SC2 Game Data Updates (R-P-S fork)

This fork uses GitHub Actions to check Blizzard's online StarCraft II game data **every four hours**. The updater cannot publish to SC2Mapster: the job checks the exact R-P-S/SC2GameData repository name, checks out this fork, and replaces the Git remote with this fork's URL before pushing.

## First run

1. Open [Actions](https://github.com/R-P-S/SC2GameData/actions) and enable workflows if prompted. Fork schedules may initially be disabled by GitHub.
2. Choose **Update SC2 Game Data** > **Run workflow**.
3. Select **dry_run = true** for the first test. This connects to Blizzard and extracts files without editing the repo.
4. If it succeeds, run again with **dry_run = false** to update the repository. Later runs are automatically scheduled.
5. If you get a permission error, check **Settings > Actions > General**, workflow permissions, and any master-branch protection rules.

The extractor uses npm package `@jamiephan/casclib@0.3.0` with online product code `s2`, region `us`. It reads `mods/core.sc2mod/base.sc2data/BuildId.txt` from CASC and compares it with the repository. If the build is unchanged it skips extraction unless **force = true**.

It extracts SC2 text/code files into a temporary folder, verifies a minimum file count, requires core files, and checks the downloaded build ID. After validation it refreshes SC2 mod/campaign directories, preserving Heroes of the Storm `.stormmod` content and `novastoryassets.sc2mod`. Git commits and pushes modified `mods` and `campaigns` only.

## Test locally

Install Node.js 24, then from the repository root:

```bash
npm install --no-save --no-package-lock @jamiephan/casclib@0.3.0
node scripts/update_sc2_gamedata.js --dry-run
```

To force a complete extraction check even when the build ID matches:

```bash
node scripts/update_sc2_gamedata.js --dry-run --force
```

This local script does not run Git or push changes.

## Known limitations

Blizzard online CASC access and the third-party native CASC package must work on GitHub's Ubuntu runner. The script has not yet been verified against a live full extraction in your fork. If the CASC listing, file names, or required files differ from expectations, the job will fail rather than commit an incomplete snapshot. Github Actions runners have finite disk, time, and bandwidth limits. The repository contains some older Heroes of the Storm data that this SC2-only updater deliberately preserves.

The fork still points to SC2Mapster as its GitHub fork parent, but **this workflow neither opens upstream pull requests nor pushes to the upstream Git remote**.
