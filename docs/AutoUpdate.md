# Automated StarCraft II and Heroes of the Storm updates

This fork uses one GitHub Actions workflow to check both Blizzard game data products **Monday-Friday at 15:17 UTC** (9:17 AM MDT / 8:17 AM MST). It does not run on Saturdays or Sundays. GitHub may start scheduled runs late.

The updater runs exclusively in **R-P-S/SC2GameData** on **master**. It neither pushes to nor opens pull requests against **SC2Mapster/SC2GameData**.

## Games

| Game | CASC product | Build ID path | Package extensions |
| --- | --- | --- | --- |
| StarCraft II | `s2` | `mods/core.sc2mod/base.sc2data/BuildId.txt` | `.sc2mod`, `.sc2campaign` |
| Heroes of the Storm | `hero` | `mods/core.stormmod/base.stormdata/BuildId.txt` | `.stormmod` |

Each extractor uses `@jamiephan/casclib@0.3.0`. It checks the build ID first, skips unnecessary extraction if unchanged, stages extracted text/code files, and validates the build ID, required files, and minimum file count before replacing files. The Heroes script never deletes SC2 mod/campaign packages and the SC2 script never deletes Heroes packages.

If either game fails extraction, no commit or push happens. After both checks succeed, any changes to `mods/` or `campaigns/` are committed and pushed only to this fork.

## Test Heroes

1. Open [your Actions page](https://github.com/R-P-S/SC2GameData/actions) and select **Update SC2 and Heroes Game Data**.
2. Click **Run workflow**, select **master** and set **Which game to check** to **heroes**.
3. Check **Extract and verify without changing repository files** (`dry_run=true`).
4. Check **Re-extract even if the build ID matches** (`force=true`).
5. Run the workflow. After it succeeds, run again with `dry_run=false` to publish an actual Heroes update.

For a manual run you can choose **both**, **sc2**, or **heroes**. Scheduled runs always check both. Manual `force` and `dry_run` default to false.

## Test locally

Install Node.js 24 and run these commands from the repository root:

```bash
npm install --no-save --no-package-lock @jamiephan/casclib@0.3.0
node scripts/update_sc2_gamedata.js --dry-run --force
node scripts/update_hots_gamedata.js --dry-run --force
```

The scripts never run Git or push independently.

## Limitations

Online extraction depends on Blizzard's CDN and a third-party native CASC library. Future Blizzard changes may require code adjustments. The workflow is limited to 180 minutes per combined job and it currently does not persist download cache between runs. For any permission problems, check the Actions write permissions and branch protection settings.

The first real Heroes extraction has not yet been run through GitHub Actions; test in dry-run mode first.
