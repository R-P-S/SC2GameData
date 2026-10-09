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


## Heroes historical Git snapshot recovery

Blizzard's CDN no longer reliably serves very old Heroes build configurations
(for example, B88481 returned CASC ERROR_FILE_NOT_FOUND).
Experimental Heroes historical recovery now reads the documented version-to-commit
mapping from jamiephan/HeroesOfTheStorm_Gamedata's VERSIONS.md.

For each Heroes build after the checked-in BuildId, the updater:
1. Selects the exact historical commit SHA listed in VERSIONS.md.
2. Fetches that Git commit, checks out its files, and extracts only Heroes
   .stormmod text/data files into a staging directory.
3. Verifies the archival BuildId.txt matches the expected historical build.
4. In non-dry-run mode, updates only Heroes packages and creates a separate
   commit/tag with the archived commit SHA in the commit message.

This makes no attempt to claim the snapshot came directly from Blizzard's CDN;
its archival source is identified explicitly. The archived repository might have
gaps. Builds not documented in that version list cannot be reconstructed by
this fallback, and no hypothetical intermediate builds are invented.

Choose game **heroes**, enable **historical** and **dry_run** to test it first.
The historical mode processes up to 3 versions per run. With dry_run disabled,
repeated manual runs can progressively catch up. Regular scheduled updates
remain on the live latest-build CASC path.


## Automatic weekday Heroes backfill (added October 2026)

The Monday-Friday 2:17 PM America/Denver workflow now handles SC2 and Heroes
independently. SC2 continues checking Blizzard's latest data and pushes its
commit/tag without waiting for Heroes.

For Heroes, until the annotated `heroes/history-complete` tag exists on the
fork, the scheduled workflow automatically fetches **up to 10 historical builds
per run** from Jamie Phan's versioned Heroes snapshots, in chronological order.
Each extracted version is checked against its BuildId and published as a separate
commit and annotated `heroes/v<version>` tag. Later scheduled runs continue
from the checked-in build. The archive list has 91 builds after the original
B76124 baseline, and the first three (through B76517) have already been
published, leaving 88 documented builds at the time of setup.

On the successful final batch, the workflow creates the
`heroes/history-complete` annotated tag. The following weekday run switches
Heroes back to its usual live CASC latest-build check. This tag marks that the
known archived backlog has been replayed; it is not a guarantee that an
undocumented Blizzard patch never existed. If an archived commit is inaccessible
or fails validation, that batch stops without a push and can be retried; SC2
commits are independent.

Normal manual runs also continue Heroes backfill while incomplete. A manual
`dry_run` validates data but publishes no commits or tags. The explicit
`historical` checkbox still enables a manual historical run once the
completion tag exists. Individual manual runs may select just SC2 or Heroes.

**Warning:** When the completion tag exists, newer Heroes patches use the
live/latest check, which may not preserve intermediate builds released between
runs. The current historical backfill recovers the known old archive only.


## Automatic StarCraft II historical updates

SC2 now uses chronological historical recovery for **every weekday scheduled
run** and every normal manual run that includes SC2. The latest-only SC2
workflow path is disabled, so a scheduled check cannot silently jump over
known intermediate builds.

It reads verified Blizzard build-config keys from BlizzTrack's historical
versions index, extracts up to **10 SC2 builds per run** (oldest first) using
online CASC, and creates a separate commit and annotated `sc2/v<version>`
tag for every recovered version. The first batch starts from whatever build is
currently checked in; at the time of setup that was B97364. Previously tested
builds include B97425, B97563 and B98310.

Unlike Heroes' finite archive catch-up, SC2 continues using historical
discovery **on future scheduled checks as well**. That preserves intermediate
patches published between two runs whenever BlizzTrack indexes their keys
and Blizzard's CDN still supplies their contents. When the historical index
is incomplete, unindexed, or a build is unavailable, SC2 fails safely instead
of falling back to the latest-only build.

This changes only the SC2 pathway. Heroes retains its automatic ten-version
weekday backfill and `heroes/history-complete` handoff. Both push only to
R-P-S/SC2GameData, with SC2 commits pushed before the independent Heroes
portion of the workflow. Use `dry_run=true` to test without publishing.


## Archived Heroes B82624 exception

The exact Jamie Phan archive commit `2d12ec29787fed3c545ebeeea4fdaeff310618f1`
for documented release 2.52.2.82624 removes `BuildId.txt` and
`DataBuildId.txt` while retaining core game-data files. The normal extraction
strictly validates `BuildId.txt`. For **only this pinned commit and build**,
the historical archive extractor creates the missing `BuildId.txt` tracking
marker from the documented version-to-commit mapping; it does not invent
missing game data or replace other source files. The exception is logged.
All unrelated missing build markers still fail validation. The successful
extraction and publication of this particular version must be verified in
an Actions run after this fix.
