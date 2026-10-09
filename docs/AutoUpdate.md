# Automated StarCraft II and Heroes of the Storm updates

The [Update SC2 and Heroes Game Data](https://github.com/R-P-S/SC2GameData/actions) GitHub Actions workflow checks Blizzard's US region **Monday–Friday at 2:17 PM Mountain Time** using the IANA timezone `America/Denver`. It adjusts automatically between **MDT and MST**. GitHub may start a scheduled run later than its configured time.

**All commits and annotated version tags are pushed only to R-P-S/SC2GameData on master.** Nothing is pushed to SC2Mapster/SC2GameData, and no upstream pull requests are created.

## Version history: separate commits and tags

Each game's newly detected build gets a **separate Git commit**. When both games changed, the workflow creates one SC2 commit, then one Heroes commit, and atomically pushes both commits and their annotated Git tags to the fork.

| Game | Commit example | Annotated tag example |
| --- | --- | --- |
| StarCraft II | `SC2: Update to 5.0.14.XXXXX` | `sc2/v5.0.14.XXXXX` |
| Heroes of the Storm | `Heroes: Update to 2.57.0.98348` | `heroes/v2.57.0.98348` |

These are examples, not claims about current game versions. The versioning script queries Blizzard's US patch/version table and verifies that the reported build ID matches the extracted CASC build. If that service is unreachable, it uses the exact build ID instead (e.g. `Heroes: Update to B98348` and `heroes/vB98348`). Tags are immutable: the script refuses to overwrite an existing tag.

The normal weekday schedule saves the **latest build available at each check**. An **experimental, manually enabled historical recovery mode** can attempt intermediate patches using BlizzTrack's archived Blizzard version manifests and CASC build-config keys. It processes up to three builds per game in chronological order, creating separate commits and tags, and does not skip a missing historical build. Recovery depends on BlizzTrack availability and Blizzard retaining those builds' CDN assets. This integration has not yet been validated end to end on GitHub Actions.

## Game extraction

| Game | CASC product | Build ID path | Package extension |
| --- | --- | --- | --- |
| SC2 | `s2` | `mods/core.sc2mod/base.sc2data/BuildId.txt` | `.sc2mod`, `.sc2campaign` |
| Heroes | `hero` | `mods/core.stormmod/base.stormdata/BuildId.txt` | `.stormmod` |

Both extraction scripts use `@jamiephan/casclib@0.3.0`. They stage and validate game files before updating the checkout, preserve the other game's package tree, and skip full extractions when the build ID is unchanged. A new build with unchanged extracted files does not generate an empty version commit.

## Manual runs

1. Open [Actions](https://github.com/R-P-S/SC2GameData/actions) and choose **Update SC2 and Heroes Game Data**.
2. Select **Run workflow** on branch `master`.
3. Choose **both**, **sc2**, or **heroes** for **Which game to check**.
4. Optionally enable **dry_run** to verify extraction without repository edits. **force** re-extracts even if the build ID matches.
5. To **test historical patches**, check the new **EXPERIMENTAL: recover missed patches in chronological order** option and enable **dry_run**. For the initial test choose one game, not both. Once a dry run succeeds, the recovery can be attempted with **dry_run** unchecked.

For safety, the weekday schedule uses the original latest-build-only mode until historical recovery has been validated. Manual runs also default to the proven latest-build mode. If history lookup is incomplete, the experimental recovery fails without publishing partial commits.

Manual runs can be started anytime, including weekends. Dry runs generate no commits or tags.

## Local testing

Use Node.js 24, then run from the repository root:

```bash
npm install --no-save --no-package-lock @jamiephan/casclib@0.3.0
node scripts/update_sc2_gamedata.js --dry-run --force
node scripts/update_hots_gamedata.js --dry-run --force
```

The extraction scripts do not perform Git operations, and the versioning helper creates local commits/tags but does not push. The GitHub Actions workflow is responsible for pushing.

## Limitations

- Existing earlier commits will not automatically be retroactively tagged. Historical recovery only attempts builds newer than the currently checked-in BuildId.
- Scheduled runs can be delayed or occasionally skipped by GitHub.
- Downloads are not persisted between hosted runner jobs.
- Blizzard's CDN and patch-version endpoints or the third-party CASC package can change; full-version lookup falls back to the build ID.
- The job has a 180-minute timeout and obeys Actions/branch protection settings.


## Recovering from an old repository baseline

Heroes currently starts at B76124 (version 2.47.3.76124), while the current
online version is much newer. BlizzTrack may not retain manifests all the way
back to the repository's baseline. The historical script now prints the oldest
and newest archived builds and checks for a coverage gap.

If the archive begins *after* the repository baseline, the default behavior is
still to **stop without updating**. For a best-effort recovery of only the
available archived builds, manually enable **Allow incomplete archive history**,
alongside **historical** and **dry_run** for a first test. If you later run
without dry_run, the first recovered commit states explicitly that some
intervening patches could not be recovered. Every available recovered build
still gets its own commit and annotated tag. The script does **not** invent
missing builds, skip failed extractions, or rewrite existing history.

The gap override is never enabled for the scheduled weekday updater.
