# miroms · Xiaomi ROM Data Repository

> 🌐 **简体中文:** [README.md](README.md) · **English:** [README_EN.md](README_EN.md)

This repository stores ROM data for all Xiaomi (Xiaomi / Redmi / POCO) devices, covering both **MIUI** and
**HyperOS** (澎湃 OS) generations, including Stable, Developer, Carrier-customized and Enterprise editions.

The data is generated automatically from a MySQL database by the Python pipeline under `scripts/` and consumed by
the [hub.miuier.com](https://hub.miuier.com) website, the admin panel and various clients.

> 本仓库存储所有小米（Xiaomi / Redmi / POCO）设备的 ROM 数据，涵盖 MIUI 与 HyperOS 两代系统，包含正式版、开发版、运营商定制版、政企版等全部分支。

---

## Repository Layout

```
.
├── api/                              # Exported JSON data (API artifacts)
│   ├── v1/devices/<codename>.json    # V1: MIUI device data (legacy format, NuxtMR site)
│   ├── v1/index.json                 # V1: homepage "this week's stable updates"
│   ├── v1/weekly.json                # V1: weekly big version → week index
│   ├── v1/weekly/week-<week>-cn.json # V1: one week (announcement + devices + changelogs)
│   ├── v1/devlist.json               # V1: device list directory (with android / miui)
│   ├── v1/sitelog.json               # V1: site log (sitelog table, site=nuxtmr)
│   ├── v1/*.json                     # V1: legacy / hand-written endpoints (see "V1 / V2 auxiliary files")
│   ├── v2/devices/<codename>.json    # V2: HyperOS device data (HyperOS.fans site)
│   ├── v2/index.json                 # V2: homepage "added in the last 6 days"
│   ├── v2/dev.json                   # V2: developer big version → week index
│   ├── v2/dev/<week>.json            # V2: one dev week (announcement + ROMs + multilingual logs)
│   ├── v2/devices.json               # V2: device list directory (with supports / android)
│   ├── v2/sitelog.json               # V2: site log (sitelog table, site=hyperos.fans)
│   ├── v2/*.json                     # V2: legacy / hand-written endpoints (see "V1 / V2 auxiliary files")
│   ├── v3/devices/<codename>.json    # V3: full device data (MIUI + HyperOS)
│   ├── v3/logs/<device>/[region/]<version>.json   # V3: multilingual changelogs
│   ├── v3/dev/index.json             # V3: developer (weekly) release index
│   ├── v3/dev/<region>/<week>.json   # V3: one dev week (announcement + devices + logs)
│   ├── v3/roms/<OS>.json             # V3: ROM lists grouped by OS (OS1/OS2/OS3…)
│   ├── v3/releases/<year>.json       # V3: ROM lists grouped by release date (year shards)
│   ├── v3/releases/index.json        # V3: release index metadata (date range / per-year stats)
│   ├── v3/index.json                 # V3: device index (device list + stats)
│   ├── v3/series.json                # V3: series data (exported from the series table)
│   ├── v3/stats.json                 # V3: recent-update stats
│   ├── v3/sitelog.json               # V3: hub's own site log (hub.web / hub.admin)
│   └── v3/tools.json                 # V3: flashing-tool downloads (converted from v1/tools.json)
├── db_structure/                     # MySQL table schemas
│   ├── devices.sql                   #   devices table
│   ├── roms.sql                      #   roms table
│   ├── logs.sql                      #   changelog table (one row shared by all languages)
│   ├── dev.sql                       #   developer (weekly) table
│   ├── branches.sql                  #   branches table
│   ├── series.sql                    #   series table
│   ├── sitelog.sql                   #   site log table (site column: nuxtmr / hyperos.fans / hub.web / hub.admin)
│   └── migrations/                   #   schema migration SQL
├── scripts/                          # sync / fetch / export / deploy scripts (Python)
│   ├── exporter.py                   #   main export script (v1 / v2 / v3 + site auxiliary endpoints)
│   ├── migrate_logs_multilang.py     #   logs table rebuild + roms.logs migration
│   ├── dedup_logs.py                 #   logs dedup audit / merge duplicate groups / prune orphan rows
│   ├── maintain_logs.py              #   unified logs maintenance: audit / content / masks / ids / orphans / counter
│   ├── proofread_logs.py             #   multilingual log proofreading: rule scan + DeepSeek review + safe writes
│   ├── fix_lang_issues.py            #   fix wrong-language columns from logs.lang_issues / clean mask bits
│   ├── fill_missing_logs.py         #   AI-translate missing languages on proofed rows
│   ├── local_translate.py           #   LM Studio (Hunyuan-MT-7B) proofread / fill translations
│   ├── restore_log_escapes.py       #   restore legacy JSON escapes ^ / $$
│   ├── fix_mixed_translations.py    #   two-step mixed_translations repair
│   ├── resequence_ids.py             #   renumber roms / dev / logs ids (remove AUTO_INCREMENT gaps)
│   ├── rebuild_roms_logs.py          #   rebuild roms.logs from the backup DB (fix dangling references)
│   ├── import_dev_week.py            #   import dev (weekly) data into dev table
│   ├── import_sitelog.py             #   import both sites' site logs into the sitelog table
│   ├── import_hub_sitelog.py         #   import hub's own (web / admin) changelog from git history
│   ├── migrate_v1v2_assets.py        #   seed v1/v2 static files / device dirs / legacy devices
│   ├── sync_devices.py               #   sync device list
│   ├── fix_missing_tag_mappings.py   #   fix missing tag mappings
│   ├── common.py                     #   backward-compat entry (re-exports the miroms package)
│   ├── config.py                     #   DB connection config + deploy config (api + ids)
│   ├── push.py                       #   one-shot export → commit & push → deploy all sites
│   ├── deploy.py                     #   trigger Cloudflare Pages deploys for config.ids
│   ├── *.py                          #   various fetch scripts (see "Fetch / Deploy Scripts")
│   └── miroms/                       #   core package (constants/utils/fetch/export, etc.)
│       ├── exporters.py              #     exportV1 / exportV2 / exportV3 / export_dev
│       └── legacy_exporters.py       #     v1 / v2 site auxiliary endpoint exports
├── CNAME                             # Github Pages domain (api.miuier.com)
├── fix_missing_tag_mappings.sql      # generated fix SQL
├── new_flags.txt / new_roms.txt      # transient fetch artifacts (safe to ignore)
├── LICENSE                           # Apache License 2.0
└── README.md
```

---

## API Data

### V1 — `api/v1/devices/<codename>.json` (MIUI only, legacy format)

One file per device, organized by branch (`branches`); ROMs inside each branch are expanded as a `links` array:

```json
{
  "codename": "agate",
  "zh-cn": "小米 11T",
  "en-us": "Xiaomi 11T",
  "ismiui": "",
  "code": "KW",
  "android": ["11.0", "12.0", "13.0"],
  "miui": ["V12.0", "V12.5", "V13.0", "V14.0"],
  "branches": [
    {
      "code": "agate_tw_global",
      "btag": "F",
      "region": "tw",
      "carrier": [""],
      "branch": "CNTP",
      "tag": "TWXM",
      "zone": 2,
      "show": 1,
      "ep": 0,
      "zh-cn": "中国台湾地区正式版",
      "en-us": "China Taiwan Stable",
      "links": [
        {
          "miui": "V14.0.5.0.TKWTWXM",
          "android": "13.0",
          "release": "2023-09-11",
          "aspatch": "2023-09-01",
          "recovery": "miui_AGATETWGlobal_V14.0.5.0.TKWTWXM_6e4377c5a1_13.0.zip",
          "fastboot": "agate_tw_global_images_V14.0.5.0.TKWTWXM_20230906.0000.00_13.0_tw_428af52e92.tgz"
        }
      ]
    }
  ]
}
```

> V1 is a legacy compatibility format covering MIUI devices only — new projects should use V3.

### V2 — `api/v2/devices/<codename>.json` (HyperOS)

A `roms` dict keyed by version number, plus a `table` header description:

```json
{
  "device": "agate",
  "name": { "zh": "小米 11T", "en": "Xiaomi 11T" },
  "code": "KW",
  "brand": ["Xiaomi"],
  "miui": "no",
  "merged": "no",
  "android": ["14.0", "13.0", "12.0", "11.0"],
  "supports": ["V14", "V13", "V12.5", "V12", "OS1"],
  "branches": [
    {
      "branchCode": "agate_tw_global",
      "brand": ["Xiaomi"],
      "device": { "zh": "小米 11T", "en": "Xiaomi 11T" },
      "idtag": "CNTP",
      "tag": "TWXM",
      "branchtag": "F",
      "name": { "zh": "中国台湾地区正式版", "en": "China Taiwan Stable" },
      "table": ["os", "android", "release", "recovery", "fastboot"],
      "show": "1",
      "carrier": [""],
      "region": "tw",
      "zone": "2",
      "ep": "0",
      "roms": {
        "OS1.0.15.0.UKWTWXM": {
          "os": "OS1.0.15.0.UKWTWXM",
          "android": "14.0",
          "release": "2025-09-15",
          "aspatch": "2025-08-01",
          "recovery": "miui_AGATETWGlobal_OS1.0.15.0.UKWTWXM_04ec99268e_14.0.zip",
          "fastboot": "agate_tw_global_images_OS1.0.15.0.UKWTWXM_20250905.0000.00_14.0_tw_1615b6324d.tgz"
        }
      }
    }
  ]
}
```

### V1 / V2 auxiliary files (NuxtMR / HyperOS.fans site endpoints)

The two reference sites each used to maintain their own data repository (NuxtMR's `public/MRData/data`, HyperOS.fans's
`public/data`) which, besides the device files, also carried a set of site-level endpoints. After migrating to this
repository:

* **Regenerated from the database** (`scripts/exporter.py` → `miroms/legacy_exporters.py`):

| File | Description |
| --- | --- |
| `api/v1/index.json` | Homepage "this week's stable updates": aggregates `roms` by ISO week (`type=MIUI`, `branch=F`, excluding `.EP.` enterprise builds) with fields `year` / `week` / `period` / `nextperiod` / `date` / `stable[{code, zh-cn, en-us, date, rom}]`; several branch versions of the same device in one week are joined with `"; "` |
| `api/v1/weekly.json` | Weekly index: `latest` / `oldest` / `versions[{version, period, weeks}]`. Weeks come from every MIUI week in the `dev` table (`region='cn'`, `show=1`), regardless of source (miuiroms / nuxtmr); `oldest` is simply the earliest week, since all weeks have a V1 single-week detail page |
| `api/v1/weekly/week-<week>-cn.json` | One week: announcement (`zh-cn` / `en-us` / `CnComID`, etc.) + `devices` list + `tpd` suspended builds + `addons` upgrade notes / release notes + `logs` module logs; the data comes from `dev` (every week whose `bigver` is MIUI, any source) and `roms.dev_week` |
| `api/v1/devlist.json` | Device directory for the list page / sitemap: brand → series → device (hand-maintained order); the script backfills `android` / `miui` from `devices/<code>.json` |
| `api/v1/sitelog.json` | Site log shaped `{"log": [{sudate, ver, zh-cn, en-us, log: [{zh-cn, en-us}]}]}`, from the `sitelog` table with `site='nuxtmr'` |
| `api/v2/index.json` | Homepage "added in the last 6 days": aggregates HyperOS ROMs by `roms.insdate` (6-day window, matching the source site), shaped `{"recent": {time, developing, roms: {<device>: {name, versions: [{insert_date, version}]}}}}` |
| `api/v2/dev.json` | Developer index: `{"HyperOS": [{bigVer, start, latest, weeks}]}`; `bigVer` is converted from `dev.bigver` (`HyperOS 1`) into the site's spelling (`HyperOS1.0`), and the weeks come from `dev` (`source='hyperos.fans'`) |
| `api/v2/dev/<week>.json` | One dev week: announcement (`title` / `postId` / `update` / `versions` / `description` / `attention` / `show`) + `roms` list + `suspended` + multilingual `logs` (`[{module: {zh, en}, log: [{zh, en}]}]`) |
| `api/v2/devices.json` | Device directory for the list page / sitemap: `mi` / `redmi` / `poco` → devices (hand-maintained `image` / `series`); the script backfills `supports` / `android` from `devices/<code>.json` |
| `api/v2/sitelog.json` | Site log shaped `{"icons": [...], "logs": [{siteVer, icon, date, log: [{zh, en}]}]}`, from the `sitelog` table with `site='hyperos.fans'` (the `icons` palette comes from the `kind='meta'` row) |

* **Maintained with the repository** (there is no database source; `scripts/migrate_v1v2_assets.py` only seeds them once and never regenerates them afterwards):
  * Hand-written content: `api/v1/tools.json`, `api/v1/thanks.json`, `api/v1/devices.json`, `api/v2/updates.json`, `api/v2/new-rom.json`
  * Archived artifacts of deprecated scripts (mostly empty fields, kept only so old clients keep working): `api/v1/log.json`, `api/v1/stable.json`, `api/v1/update.json`, `api/v1/update_full.json`, `api/v1/newrom.json`
  * Device images: **not copied** — the canonical location is the repository-root `images/` (site root `https://api.miuier.com/images/<file>`, which is what the frontend's `buildDeviceImageUrl()` uses). The reference sites' `assets/images/**` matches it file-for-file (382/382, including all 247 images referenced by `api/v2/devices.json`), so copying them again into `api/v2/assets/images/**` would be pure duplication (~25 MB); use `migrate_v1v2_assets.py --with-images` to restore the old layout if ever needed.
  * Legacy devices that exist only in the reference repositories and have no record in the `miroms` database (`devices/<codename>.json`):
    V1: `HM2013023` / `HM2014011` / `HM2014501` / `camellian` / `cannong` / `ido` / `laurel` / `lcsh92` / `lcsh92_wet_tdd` / `mione` / `pond`,
    V2: `arctic` / `chicago` / `coral` / `donghai` / `moscow` / `pissarro_in` / `pond` / `suiren` / `yupei_d`

> Known differences from the reference repositories after migration (all expected, because regeneration is
> database-first):
> device names come from `devices.full_names` (they may also carry an alias such as POCO, e.g. `blue` = "POCO C61 / Redmi A3");
> `dev.bigver` is normalised to `MIUI V6` (the V1 weekly index maps it back to the historical spelling `MIUI 6`);
> the V1 weekly list also includes devices that are bound to a `dev_week` in the database but were not listed by the source file, and drops fully duplicated rows from the source file;
> English weekly logs follow the official translations in the `logs` table (the source files were hand-translated);
> the V1 weekly announcement fields `no` (a hand-written device shorthand, present in 30 of the 54 source weeks), `vid`, `showdevices` and `CnBBSID` / `GbBBSID` (always empty in the source files) have no counterpart column in the database, so the export always emits an empty string / `"1"` — the frontend does not use any of these fields today.

### V3 — `api/v3/devices/<codename>.json` (full, recommended)

Covers both MIUI and HyperOS; adds a nested `tags` field and separate changelog files:

```json
{
  "device": "agate",
  "name": { "zh": "小米 11T", "en": "Xiaomi 11T" },
  "code": "KW",
  "brand": ["Xiaomi"],
  "android": ["14.0", "13.0", "12.0", "11.0"],
  "supports": ["OS1", "V14", "V13", "V12.5", "V12"],
  "branches": [
    {
      "id": "agate_tw_global",
      "brand": ["Xiaomi"],
      "device": { "zh": "小米 11T", "en": "Xiaomi 11T" },
      "name": { "zh": "中国台湾地区正式版", "en": "China Taiwan Stable" },
      "region": "tw",
      "carrier": [""],
      "tags": { "branch": "CNTP", "tag": "TWXM", "branchtag": "F", "btag": "F" },
      "zone": "2",
      "show": "1",
      "ep": "0",
      "roms": [
        {
          "miui": "OS1.0.15.0.UKWTWXM",
          "android": "14.0",
          "release": "2025-09-15",
          "aspatch": "2025-08-01",
          "recovery": "miui_AGATETWGlobal_OS1.0.15.0.UKWTWXM_04ec99268e_14.0.zip",
          "fastboot": "agate_tw_global_images_OS1.0.15.0.UKWTWXM_20250905.0000.00_14.0_tw_1615b6324d.tgz"
        }
      ]
    }
  ]
}
```

### V3 auxiliary files

| File | Description |
| --- | --- |
| `api/v3/logs/<device>/[region]/<version>.json` | Multilingual changelog for a single ROM; region-tagged versions live in a `region` subdirectory. `logs_zh` / `logs_en` are always present, other languages appear only when translated: `{"logs_zh": {...}, "logs_en": {...}, "logs_zh_tw": {...}, "logs_ja": {...}, ...}` (see `CHANGELOG_LOCALES` in `scripts/miroms/constants.py`; all 21 match the site's locales) |
| `api/v3/dev/index.json` | Developer (weekly) index: `latest` / `oldest` / `regions` plus a `weeks` list (week, region cn/global, big version, version, zh/en title, release date, device count, available languages) |
| `api/v3/dev/<region>/<week>.json` | One developer week: announcement title/body/notes, `devices`, `roms` and multilingual `logs` (same shape as `v3/logs/**`) |
| `api/v3/roms/<OS>.json` | ROM lists grouped by OS major version (e.g. `OS1.json` = HyperOS 1); each entry has device, version, Android, region, branch name, dates and package filenames — combine by version to build per-device ROM tables |
| `api/v3/releases/<year>.json` | ROM lists grouped by release date: `{"year": "2026", "dates": {"2026-09-18": [{"device": "brussels", "version": "OS3.0.308.0.WDRMIXM", "region": "global"}, ...]}}`; year shards let the frontend fetch only what a date query needs |
| `api/v3/releases/index.json` | Release index metadata: `generatedAt`, queryable range (`minDate` / `maxDate`), `totalRoms` and per-year `years` stats (ROM and active-day counts) |
| `api/v3/index.json` | Device index: name, brand, series (`series`), code, Android versions, supported systems, regions (`regions`), carriers (`carriers`), region-to-carrier mapping (`regionCarriers`, e.g. `{"cn": ["chinatelecom", ...]}`), branch count (`branchCount`) and ROM count (`romCount`) per device |
| `api/v3/series.json` | Series: series list (brand, zh/en names, `device_ids` membership) plus device ordering (`order`) |
| `api/v3/stats.json` | Recent stats: `generatedAt` generation time, `recentDays` window, `recentRoms` recent additions count, `recent` recent ROM detail list |
| `api/v3/sitelog.json` | hub's own site log: `{"generatedAt", "sites": {"hub.web": {site, latest, count, logs}, "hub.admin": {...}}}`, each entry shaped `{ver, date, log: [{zh, en}]}` (newest version first). Entries are imported into the `sitelog` table from git history by `scripts/import_hub_sitelog.py` and then exported; the website frontend reads `sites['hub.web']` while the admin panel connects straight to the database and reads `site='hub.admin'` |
| `api/v3/tools.json` | Flashing-tool downloads (for the website's "tool downloads" page): `{"generatedAt", "source", "tools": [{tool, name: {zh, en}, packages: [{version, date, filename, url, attentions: [{zh, en}], logs: [{zh, en}]}]}]}`; the hand-maintained `api/v1/tools.json` is the only hand-written source, and the export converts `zh-cn` / `en-us` into `zh` / `en` and `FileName` into `filename` |

### Multilingual changelogs

Changelogs come from `update.miui.com`: the `l` field in the request form selects the language, and locales Xiaomi has no translation for fall back to English. Use `--probe` first to confirm which locale the API actually honours — Arabic, for example, is only translated for `ar_EG`; `ar` / `ar_SA` / `ar_AE` all fall back to English. Workflow:

1. Register the locale in `CHANGELOG_LOCALES` (`scripts/miroms/constants.py`: column / API locale / site locale)
2. Add the matching column to the `logs` table (schema: `db_structure/logs.sql`; the column set follows `CHANGELOG_LOCALES` automatically — the `roms` table no longer needs to change)
3. `python3 scripts/fetch_changelog.py --probe 5` to see which locales actually return a distinct translation (no writes)
4. `python3 scripts/fetch_changelog.py --langs ja,ko,ru` to fill specific locales; without arguments every locale is processed in order
Processing is batched by ROM id: each locale first collects its own array of pending ids, then the union of ids is walked once — a ROM's row is queried once and its request form is built once, so a ROM present in several locales only swaps the `l` parameter for each extra request and is removed from those arrays right after, avoiding duplicate queries and duplicate requests.

Writes are per-row `UPDATE`s on an `autocommit` connection, so each one lands immediately (nothing is batched into a final commit). On startup the script prints the database it actually connects to and verifies that every locale column exists — a missing column aborts with the migration command instead of being swallowed silently; failed writes are counted as `write_failed` and the first error is printed, so it can no longer report "N written" while the table stays untouched. When nothing was written the script lists the likely causes: the API fell back to English for every locale (check with `--probe`, or force with `--force`), the pending arrays are empty (`--min-id` too high), or the database rejected the writes. `--dry-run` shows what would be written without touching the DB.

Locales that fall back to English are skipped automatically (column stays NULL) so the table does not fill with English copies; use `--force` to store them anyway.

Existing logs are left untouched by default (only missing locales are filled). Add `--verify` to check stored translations against the official API: when the API returns a distinct translation for that locale and it differs from the database, the official text is written back (AI-translated wording and missing/extra entries are corrected to the official structure). If the API only falls back to English or has no changelog, the stored translation is kept, so AI translations are not replaced with English. `--verify-only` checks without filling, `--verify-limit` caps records per locale, and `--min-id` / `--max-id` split the work into ranges. A full verification takes roughly 170k requests, so batch it:

```bash
python3 scripts/fetch_changelog.py --verify --langs ja,ko,ru --verify-limit 200
python3 scripts/fetch_changelog.py --verify-only --min-id 0 --max-id 30000
python3 scripts/fetch_changelog.py --verify --dry-run --limit 5 --verify-limit 5
```

Pure corrections never touch `release_date`; it is only updated when a ROM had no changelog at all and gets its first one (filling an extra locale for an old ROM does not change it either).

#### AUTO_INCREMENT gaps

InnoDB never reclaims an `AUTO_INCREMENT` value after a failed insert or a rolled-back transaction, so occasional
failures in the scrapers burn ids — and note that this project, HyperOS.fans and NuxtMR **all write to the same
`miroms` database** (each has its own `scripts/config.py` pointing at it), so gaps accumulate slowly (`roms` once had
54,622 rows but had already reached id 54,634). Avoid `INSERT ... ON DUPLICATE KEY UPDATE` for upserts in importers
for the same reason — a duplicate-key hit also advances the counter (the `dev` importer used to burn hundreds of ids
per run and now does a lookup followed by `UPDATE`).

```bash
python3 scripts/resequence_ids.py                 # report gaps in roms
python3 scripts/resequence_ids.py --table dev     # report gaps in dev
python3 scripts/resequence_ids.py --table logs    # report gaps in logs (renumbering rewrites references)
python3 scripts/resequence_ids.py --apply         # renumber roms and reset the counter
python3 scripts/resequence_ids.py --table logs --apply
python3 scripts/resequence_ids.py --verify        # verify density only
```

`logs.id` is referenced by `roms.logs` / `dev.logs`, so it cannot be renumbered like `roms` / `dev`.
`--table logs` uses `LogMaintenance.compact_ids`: inside a single transaction it shifts every id by
+1000000, assigns `ROW_NUMBER()`, rewrites all references from the old→new map and resets the counter.
The whole run happens under the cross-process write lock, and the logs table plus all references are
backed up to JSON before writing (`--no-backup` skips it).

#### Log maintenance (dedup / content / masks / ids / orphans)

The shared logic lives in `LogMaintenance` (`scripts/miroms/logs_maintenance.py`) and the text
predicates in `LogText` (`scripts/miroms/logs_text.py`); the CLI only parses arguments and prints:

```bash
python3 scripts/maintain_logs.py                        # read-only audit: duplicates, dangling refs,
                                                        # bad JSON, orphans, content mismatch,
                                                        # stale hashes, masks, id gaps
python3 scripts/maintain_logs.py --report /tmp/audit.json
python3 scripts/maintain_logs.py content --apply        # rebuild content / content_hash from logs_zh
python3 scripts/maintain_logs.py masks --apply          # new mask = old mask | common language mask
python3 scripts/maintain_logs.py masks --clean-invalid --apply  # drop mask bits whose module text is gone
python3 scripts/maintain_logs.py prefix --apply          # strip leading whitespace/punctuation (except `*`)
python3 scripts/maintain_logs.py ids --apply            # compact logs ids + rewrite refs (auto backup)
python3 scripts/maintain_logs.py unused --apply         # delete unreferenced log rows
python3 scripts/maintain_logs.py auto-increment --apply # reset logs.AUTO_INCREMENT to MAX(id)+1
python3 scripts/maintain_logs.py merge --groups "11040:1" --apply  # explicit group merge (rewrites refs)
python3 scripts/maintain_logs.py snapshot --out /tmp/logs_before.json.gz
python3 scripts/maintain_logs.py compare --before /tmp/logs_before.json.gz
```

Every action is a dry-run unless `--apply` is given. Mask filling only adds bits, so no ROM's export
can regress; `ids` / `unused` are destructive and refresh the export cache afterwards.

`merge` covers the cases the automatic dedup cannot decide: the same Chinese log, but one side's
foreign text is only an English fallback (equal to that row's `logs_en`, e.g. `id=1` has
`logs_de='Other'`) while the other side has a real translation (e.g. `id=11040` has
`logs_de='Sonstiges'`). The strict rule treats the fallback as a conflict; `merge_groups` prefers the
real translation, fills the remaining gaps with fallbacks, and rewrites references to the
representative row.

`snapshot` exports the localized logs of every `roms` / `dev` row (gzipped by default, ~80–90 MB);
run `compare` after dedup / mask filling / id compaction to diff "added / removed texts, languages and
module names" per row. It exits with code 1 when content is lost (a text disappears, a language
disappears or a whole row disappears), which is the same export-regression check the earlier one-off
scripts used, but repeatable.

Pure logic (text predicates, dedup plan, reference remapping, content / mask / orphan checks) has
unit tests that need no database:

```bash
python3 scripts/test_logs_maintenance.py
```

#### AI proofreading (DeepSeek, optional)

Different language structures of one ROM are stored as a "Chinese cluster + extra language clusters".
The earlier heuristic that filled Chinese by module name / entry count could fill the wrong name:
`id=11036` (`Interkonnektivität`) and `id=11038` (`Datenschutz und Sicherheit`) were both labelled
"其他", while the real "other" is `id=11040` (`Sonstiges`). This creates duplicate Chinese modules in
one ROM and duplicated lines in the zh export. `proofread_logs.py` turns the repair into a repeatable
pipeline (dry-run by default):

```bash
# 1) check specific logs.id (does not change content; marks proofed when verdict=ok)
python3 scripts/proofread_logs.py check --ids 11036
python3 scripts/proofread_logs.py check --ids 11036,11038
python3 scripts/proofread_logs.py check --ids 3788 --no-ai          # rules only (fallbacks / swapped columns)
python3 scripts/proofread_logs.py check --ids 2998 --json /tmp/check.json

# 2) full scan → AI review → plan → write
python3 scripts/proofread_logs.py scan --report /tmp/proofread_scan.json
python3 scripts/proofread_logs.py review --scan /tmp/proofread_scan.json \
        --cache /tmp/proofread_cache.json --decisions /tmp/proofread_decisions.json
python3 scripts/proofread_logs.py apply --decisions /tmp/proofread_decisions.json --allow-clear
python3 scripts/proofread_logs.py apply --decisions /tmp/proofread_decisions.json --allow-clear --apply
```

`check` is the single-row check (content untouched; only the proofed flag is updated): it prints `content` / `zh` / all language texts, English
fallback columns, suspected swapped columns, the Chinese module names seen in the same ROM, then the AI
`verdict` (ok / wrong_zh / mixed_translations / extra_module), suggested Chinese, confidence and reason.
Add `--decisions /tmp/fix.json` to save module `wrong_zh` verdicts as a decisions file for `apply`
(dry-run by default).

Batch proofreading has three tiers; all of them **estimate only** unless `--run` is passed:

```bash
# tier 1: conflict families only (recommended first; ~0.6M tokens)
python3 scripts/proofread_logs.py review --limit 0 --decisions /tmp/f_decisions.json

# tier 2: every multilingual row, 10 rows per call (~2.5–3.0M tokens, ~400 calls)
python3 scripts/proofread_logs.py batch-review --batch-size 10
python3 scripts/proofread_logs.py batch-review --batch-size 10 --run

# tier 3: one row per call over all rows (not recommended: 11–20M tokens, ~11k calls;
#         includes 7,156 single-language rows that cannot be cross-checked)
python3 scripts/proofread_logs.py batch-review --batch-size 1 --all
python3 scripts/proofread_logs.py batch-review --batch-size 1 --all --run --allow-expensive
```

`batch-review` behaviour:

- by default only rows with **≥2 languages** (3,918 rows); `--all` includes single-language rows;
- prints rows / batches / prompt / completion / total token estimates and ETA first; without `--run`
  nothing is sent;
- above 8M tokens or 5,000 calls it requires `--run --allow-expensive`;
- `--limit-rows N` to sample, `--cache` to resume, `--types module,log` to restrict;
- results go to `--decisions` for `apply`; **log-entry Chinese is report-only** and never auto-written;
- AI findings are persisted **after every batch** (`lang_issues` / `proofed`), so an interrupted 11k-row run keeps its progress.

`proofed` flag: `review` / `batch-review` / `check` mark `proofed=1` only when `verdict=ok` **and there is
no language mismatch**; later scans skip it. Any content change (language fill, merge, content rebuild,
`apply` rename/clear) resets `proofed`, `complete` and `lang_issues`, so the row is re-audited.

`complete`: 1 only when **all language columns are present and `proofed=1`**; reset to 0 when proofed is
cleared, languages are changed/removed, or any language is missing. Recompute with
`python3 scripts/maintain_logs.py complete --apply`.

Language check: every AI review also checks, per non-empty language column, whether the text is really in
that language (mapping in `LogProofreader.LANG_NAMES`). Mismatches go into `logs.lang_issues`; in addition,
a non-English column whose value is identical to `logs_en` is annotated as an English fallback with
confidence 0.75 (an explicit AI finding wins). Rows with `lang_issues` are never marked `proofed=1`.
`check` prints annotations like `logs_de 实际='英文' (0.98) ...`. Use `check --force` to re-audit a marked
row, and `--no-mark` to write nothing at all.

Restore legacy escapes:

```bash
python3 scripts/restore_log_escapes.py            # preview
python3 scripts/restore_log_escapes.py --apply    # write (backup first)
```

The old writer turned `'` / `"` into `^` and `%` into `$$`; column storage no longer needs it.
Examples: `won^t → won't`, `l^écran → l'écran`, `^Service & feedback^ → "Service & feedback"`,
`^^text^^ → "text"`, `5$$ → 5%`. Proofed / complete / lang_issues are kept by default.

Fill missing languages on proofed rows:

```bash
python3 scripts/fill_missing_logs.py                    # list gaps + token estimate
python3 scripts/fill_missing_logs.py --ids 23           # one row only
python3 scripts/fill_missing_logs.py --expected owners  # only languages present in refs
python3 scripts/fill_missing_logs.py --run              # AI preview, no writes
python3 scripts/fill_missing_logs.py --apply            # AI translate + write (backup first)
python3 scripts/fill_missing_logs.py --apply --keep-proofed

# chunked: --offset / --limit (one process per chunk)
python3 scripts/fill_missing_logs.py --offset 0 --limit 20 --apply --keep-proofed --max-calls 20
```

- Expected languages default to all columns; `--expected owners` limits to languages present in the
  row's `roms` / `dev` masks;
- Translates from `logs_zh` / `content` / `logs_en`; results below `--min-confidence` (0.8) are skipped;
- A translation identical to the English source is rejected (avoids writing English fallback again);
- with `--apply`, each row is written **immediately after its translation arrives**; `--atomic` writes
  only after the whole run;
- `proofed` is reset to 0 after filling (new text needs review); `--keep-proofed` keeps it when no
  `lang_issues` remain;
- Filled columns are removed from `lang_issues`, set to NULL when empty; cache supports resume.

Fix language columns from the annotations:

```bash
python3 scripts/fix_lang_issues.py                       # preview every annotated row
python3 scripts/fix_lang_issues.py --ids 1,165           # specific logs.id only
python3 scripts/fix_lang_issues.py --apply               # replace with AI `correct` (no correct = keep)
python3 scripts/fix_lang_issues.py --mode translate --apply # AI-translate entries without correct (writes each row immediately)
python3 scripts/fix_lang_issues.py --mode hybrid --apply # clear only when there is no correct
python3 scripts/fix_lang_issues.py --mode clear --apply  # explicitly NULL wrong-language cells
python3 scripts/fix_lang_issues.py --mode move --apply   # move to an empty correct column
python3 scripts/fix_lang_issues.py --clean-masks --apply # also drop mask bits
```

- Default `--mode correct`: replace only when the annotation has `correct` and
  `confidence >= --min-confidence` (default 0.8); without a correct value the original text is kept
  and the annotation remains — nothing is deleted;
- `--mode hybrid` clears only when there is no correct value; `--mode clear` is explicit deletion;
- `logs_zh` / `logs_en` are untouched unless `--allow-core` (replacing/clearing a core column rebuilds
  `content` / `content_hash`);
- fixed entries are removed from `lang_issues`; when everything is fixed the column is explicitly set to `NULL`, and `proofed` is reset to 0;
- `--clean-masks` removes the cleared languages from `roms` / `dev` reference masks;
- a backup is written before applying; run `maintain_logs.py snapshot` / `compare` to review export impact.

- `scan`: rules only, no AI. Finds families where one ROM has several module rows with the same Chinese
  name but conflicting real translations (English fallbacks equal to the row's `logs_en` are ignored);
  also reports suspected swapped language columns using "translation → Chinese" co-occurrence.
- `review`: one DeepSeek call per family; the model first returns a `verdict`:
  `ok` / `wrong_zh` (Chinese is wrong and all real translations point to another Chinese name) /
  `mixed_translations` (Chinese may be right, but translations of different languages belong to
  different modules = misaligned/swapped columns) / `extra_module`. `wrong_zh` may only pick a Chinese
  name present in that ROM; `extra_module` returns null. Prompts are cached by content hash and resumable.
- `apply`: `rename` fixes full rows (with `logs_en` and many languages); `clear` removes Chinese from
  narrow extra-cluster rows (no `logs_en`, ≤6 languages) and drops the zh mask bit; `mixed_translations`
  is report-only (swapping columns needs a separate repair); low-confidence / conflicting / non-allowed
  actions are only reported. Rows with many languages but no `logs_en` (possibly legitimate clusters) are
  report-only even if the AI flags them: clearing such rows was measured to drop Chinese entry texts that
  only exist in some ROMs. A backup is written before any write; then run `maintain_logs.py audit` and
  `snapshot` / `compare`.

API key (environment variable wins):

```bash
export DEEPSEEK_API_KEY=sk-...
# or set deepseek_api_key in data/scripts/config.py (plus deepseek_base_url / deepseek_model)
```

Cost control: `review --limit N`, `--max-calls N`, `--cache`; pass `--all` to review non-priority
families as well (by default only "narrow row / missing en" high-risk families are reviewed).

```bash
python3 scripts/test_logs_proofread.py
```

#### Local proofreading / filling (LM Studio + Hunyuan-MT-7B)

Hunyuan-MT-7B is a pure translation model: use it to fill missing languages one entry at a time,
and to proofread existing translations by re-translating and comparing. Load the model in LM Studio,
click Start Server (default `http://127.0.0.1:1234`); the script uses LM Studio's native
`POST /api/v1/chat` (`system_prompt` carries the instruction, `input` carries the source text)
and needs no API key:

```bash
python3 scripts/local_translate.py check --probe              # server / model / smoke test
python3 scripts/local_translate.py fill --limit 50            # inventory only (no model calls)
python3 scripts/local_translate.py fill --ids 146 --run       # preview fills
python3 scripts/local_translate.py fill --ids 146 --apply     # write fills (backup first)
python3 scripts/local_translate.py review --langs logs_en --limit 200 --run
python3 scripts/local_translate.py review --langs logs_en --ids 146 --fix
python3 scripts/local_translate.py all --limit 200 --apply --fix
```

- API mode: native `/api/v1/chat` by default; pass `--api openai` (or set `LMSTUDIO_API=openai` /
  `lmstudio_api` in `config.py`) for the OpenAI-compatible `/v1/chat/completions`; the base URL always
  points at the server root (`http://127.0.0.1:1234/v1` is also recognised);
- Prompts follow the official templates: Chinese directions use `把下面的文本翻译成<目标语言>，不要额外解释。`, other directions use the English template;
- Output validation: placeholders (`%s` / `{0}`), prompt echo, Han characters in non-Chinese columns, target-script characters (ru / uk / ar / ug / bo / th / hi / ja / ko);
- Proofreading: re-translate the source and compare with the existing translation; long text below `--ratio` (0.75) or short text below `--short-ratio` (0.45) is flagged, and only `--fix` replaces it;
- Writes go through `LogFiller.apply()`: automatic backup, `lang_issues` cleanup, `proofed` reset to 0; `--expected owners` fills only languages referenced by ROMs, `--workers` adds concurrency, `--cache` reuses results.

#### Log deduplication (always verified)

`logs` rows are shared across ROMs, and the write path matches by **"same type + no language conflict"**:
before writing, the whole `logs` table is loaded into an in-memory row pool (`LogStore.load_index`) and an
existing group is reused whenever its language texts do not conflict — so the same log is recognised even when
the primary content differs (`#25 content=相册` vs `#27 content=Gallery`), unlike the early implementation that
only looked rows up by `content_hash`.

The following guards report duplicates and fail loudly:

| Where | What |
| --- | --- |
| `python3 scripts/dedup_logs.py` | Lists mergeable groups; `--apply` merges, `--prune-unused` removes orphan rows |
| `python3 scripts/maintain_logs.py` | One-shot read-only audit: duplicate groups, dangling refs, bad JSON, orphans, content mismatch / stale hashes, extendable / invalid mask bits, id gaps |
| `import_dev_week.py` / `migrate_logs_multilang.py` | Call `LogStore.duplicate_report()` at the end and exit non-zero when duplicates are found |
| Admin `/logs` page → "dedup audit" | `GET /api/logs/audit`: duplicate groups, duplicate rows, unreferenced rows |

The duplicate predicate is "same Chinese log text, same type, no conflicting language texts".
`dedup_logs.py` is only the CLI for `LogMaintenance.duplicate_plan` / `apply_duplicates`, and the admin
audit uses the same algorithm (`findDuplicateLogGroups` in `app/admin/server/utils/logs.ts`), so the
CLI, the admin page and the Python maintenance class always agree.
Merging unions the language texts, so `maintain_logs.py masks --apply` can afterwards add the newly
common language bits to the masks (add-only).

Rule: same type, no conflicting language text, at least one shared language text → they are the same row.
Merging only unions texts and rewrites references; language masks stay untouched, so every ROM still exports
byte-for-byte the same content.

#### Log storage: one row per log, shared by all languages

`roms` used to carry 21 `logs_*` columns (one per language) where each translation of the same line was deduplicated
separately and never linked. The new layout is:

* **`logs` table** — one row per log, shared by every language version: `id` / `type` (`module` or `log`) /
  `content` (primary text, Chinese first, English when no Chinese exists) / `content_hash` (`md5(content)`) /
  `logs_zh`, `logs_zh_tw`, `logs_en` … `logs_bo` (the per-language texts).
* **`roms.logs`** — a single language-neutral ID structure `[[moduleId, [entryId, ...], langMask], ...]`. The mask is
  a 21-bit integer (bit *i* = the *i*-th locale column) recording which languages that position actually belongs to
  in that ROM. Adding a locale no longer touches `roms`.

Two rules make this safe (both in `scripts/miroms/logs_store.py`):

1. **Shape clustering** — module/entry indexes of the Chinese log do not always line up with other languages
   (e.g. Chinese has 电话 / 联系人 / 短信 / 便签 while Japanese and German only return a single 「其他」 module).
   Languages are therefore only merged positionally when their *structure fingerprint* is identical; other languages
   form their own group and are appended to the master log, so logs mentioned only by other languages are kept.
2. **Language mask + conflict splitting** — `logs` rows are shared across ROMs, so the mask stops a module from one
   language leaking into another language's output; when the same primary text has conflicting translations in
   different ROMs the row is split instead of overwriting, so every ROM round-trips exactly.

> Migration: `python3 scripts/migrate_logs_multilang.py` (the old table is renamed to `logs_legacy`; drop it once you
> are happy). The migration was cross-checked against an independent restore of the pre-migration backup: all
> 470,542 "ROM × language" structures decode byte-for-byte identically.
>
> Normalisation: leading/trailing whitespace is trimmed from the primary text (the legacy data had 91 entries that
> differed only by trailing spaces), so a handful of exported lines no longer carry stray spaces.

#### Developer (weekly) releases

The `dev` table stores one row per week and region — `region=cn` (zone 1) for China and `region=global` (zone 2) for
the global build, so the same week can have two independent announcements, logs and device lists. Schema:
`db_structure/dev.sql`.

```bash
python3 scripts/import_dev_week.py --source hyperos    # HyperOS.fans/public/data/dev/<week>.json
python3 scripts/import_dev_week.py --source nuxtmr     # NuxtMR/public/MRData/data/weekly/week-<week>-cn.json
python3 scripts/import_dev_week.py --source miuiroms   # MIUIROMS/weekly/logs/week-<week>-CN.html
python3 scripts/import_dev_week.py --all --dry-run     # every source, no writes
python3 scripts/import_dev_week.py --backfill-roms     # only backfill roms.dev_week by release date
```

`dev` stores **no device/ROM JSON** (the old `devices` / `roms` columns held ~1.2 MB of duplicated data and were
dropped — see `db_structure/migrations/20261016_dev_drop_json.sql`). A week's device list *is* the `roms` relation:

```sql
SELECT r.device, r.version, r.android, r.release_date, r.recovery, r.fastboot
  FROM roms r
  JOIN dev d ON d.week = r.dev_week AND d.zone = r.zone
 WHERE d.week = 500 AND d.region = 'cn';
```

Device names come from `devices`, while version / Android / release date / package filenames come from `roms`, so the
exporter and the admin binding page both derive the lists on the fly. Binding (`roms.dev_week`) uses three rules: the
week's version number (primary), per-device versions from the announcement table (secondary), then branch + zone +
release date (fallback); weeks that still cannot be matched are bound by hand in the admin "dev binding" page.

```bash
# (commands above)
```

Logs go through the same pipeline (Chinese structure first, `dev.logs` stores the language-neutral ID structure).
The English text in the metadata is a hand translation that differs from the official one, so the importer first
looks the Chinese text up in `logs` and prefers the official English; only when nothing is found does it keep the
metadata translation. `expand_mask=True` widens the language mask to the languages shared by the module and all its
entries, so reusing an already-translated group also surfaces translations beyond Chinese and English. Device
matching prefers the metadata's `device + version`; sources without a device list (HTML) fall back to
`branch='X'` + region + release date.

In the MIUIROMS HTML pages the device list is a separate `<table>`: it is stripped before the changelog text is
extracted (otherwise its rows leak into the log body as `机型 / 卡刷包 / miui_XXX.zip` junk — which did happen),
and parsed into `devices` / `roms` instead (a `(cepheus)` suffix in the model name is used directly as the
codename, otherwise the name is looked up in the `devices` table). The `▍发布时间` section is split into
`release_date` / `versions` / `bigver` with the original line kept in `description`, and the parser counts and
warns about suspicious "table-like" entries.


#### Site log (sitelog table)

The site logs of the two reference sites used to be hand-written in their own repositories, in different shapes:

* NuxtMR: `{"log": [{sudate, ver, zh-cn, en-us, log: [{zh-cn, en-us}]}]}`
* HyperOS.fans: `{"icons": [...], "logs": [{siteVer, icon, date, log: [{zh, en}]}]}`

hub's own changelogs (the website frontend `hub.web` and the admin panel `hub.admin`) are instead derived straight
from git history: the repository has no git tags, so **versions are grouped by commit date** — the commits of each
project under its path are grouped by author date and numbered ascending `V0.1.0`, `V0.2.0`…, the newest one being the
current version (git history only appends at the end, so existing version numbers stay stable). Commit titles have the
`[web]` / `[admin]` / `[root]` / `[data]` prefixes and `feat(web):`-style scopes stripped, since they are redundant
for the project.

They now live in a single `sitelog` table (see `db_structure/sitelog.sql`), with a `site` column to tell the sites
apart and a `kind` column for the row type:

```bash
python3 scripts/import_sitelog.py --all                  # reference sites (nuxtmr 76 rows + hyperos.fans 45 rows)
python3 scripts/import_sitelog.py --source nuxtmr        # NuxtMR only
python3 scripts/import_sitelog.py --dry-run              # stats only, no writes

python3 scripts/import_hub_sitelog.py --dry-run          # hub itself: preview the version split of both projects
python3 scripts/import_hub_sitelog.py                    # hub itself: hub.web 17 versions + hub.admin 13 versions
python3 scripts/import_hub_sitelog.py --drop-types chore,build,docs   # keep only user-facing commits such as feat/fix
```

* `kind='entry'` are log entries: `ver` / `icon` / `log_date` / `devices_zh` / `devices_en` / `logs` (`[{"zh","en"},...]`); the smaller `sort_order` comes first (0 = newest).
* `kind='meta'` is site-level metadata: currently only the HyperOS.fans `icons` palette (unused by the frontend, kept to preserve the source site's data).
* Site version numbers may repeat (NuxtMR has two `V0.5.5-SNAPSHOT` and two `V0.3.8-SNAPSHOT` rows), so the unique key includes `log_date`.
* Git-derived entries only fill `en` when the title itself contains no CJK characters and leave it empty otherwise — the frontend falls back to Chinese when a translation is missing.
* All writes go through `miroms/sitelog_store.py` (an in-place UPDATE by unique key, so no AUTO_INCREMENT ids are burned).
* On export each site is restored to its original shape: `export_sitelog('nuxtmr')` → `api/v1/sitelog.json`, `export_sitelog('hyperos.fans')` → `api/v2/sitelog.json`; importing and re-exporting round-trips the source files field for field (verified); `export_hub_sitelog()` → `api/v3/sitelog.json` (the hub.web / hub.admin lines).

---

## Database Schema

MySQL (InnoDB, utf8mb4); table structure and field meanings are in `db_structure/`:

- **`devices.sql`** — devices: codename (`device`), internal id (`devtag`), device code (`code`), ROM tag (`tag`),
  region (`region`), carrier (`carrier`), brands (`brands` / `full_brands`), zh/en names (`full_names` / `names` /
  `xiaomi` / `redmi` / `poco`), image (`image`), launch date (`launch_date`)
- **`roms.sql`** — ROMs: system type (`type`: MIUI / HyperOS), major version (`bigver`), region, tag, branch
  (`branch`: F=Stable / X=Developer), full version (`version`), Android version, release dates (`beta_date` /
  `release_date` / `public_date`), Recovery / Fastboot / carrier package filenames (`recovery` / `fastboot` /
  `ctelecom` / `cmobile` / `cunicom` / `others`), changelog (`logs`, a single language-neutral ID structure
  `[[moduleId,[entryId,...],langMask],...]`), developer week (`dev_week`), security patch date (`aspatch`)
- **`logs.sql`** — changelogs: one row per log shared by every language version (`type` module/log, `content`
  primary text with Chinese first, `content_hash`, `proofed` (1 = AI-verified consistent; scans skip it), `complete` (all language columns present and proofed=1), `lang_issues` (JSON annotations such as `{"logs_de":{"detected":"英文","confidence":0.98}}`; rows with annotations are never proofed), plus 21 `logs_xx` language columns)
- **`dev.sql`** — developer (weekly) releases: unique on `week` + `region` (cn / global), holding the announcement,
  upgrade notes, device/ROM lists and the language-neutral `logs` ID structure
- **`branches.sql`** — branches: branch type, zh/en names, tag (`tag`), code suffix (`code`), version code
  (`vercode`), carrier, region, zone (`zone`), visibility (`visibility`), enterprise flag (`ep`)
- **`series.sql`** — series: brand (`brand`: xiaomi / redmi / poco), zh/en names (`name_zh` / `name_en`), device
  membership (`device_ids`, JSON array), ordering (`sort_order`)
- **`sitelog.sql`** — site log: `site` identifies the site (`nuxtmr` → `api/v1/sitelog.json`, `hyperos.fans` →
  `api/v2/sitelog.json`, `hub.web` / `hub.admin` → `api/v3/sitelog.json`) and `kind` the row type (`entry` log entry /
  `meta` site-level metadata such as the `icons` palette), holding the version (`ver`), icon (`icon`), date
  (`log_date`), new-device summary (`devices_zh` / `devices_en`) and log body (`logs`, `[{"zh","en"},...]`)

---

## Scripts

`scripts/` is pure Python 3 (no third-party dependencies), modular structure:

| File | Description |
| --- | --- |
| `exporter.py` | Entry script: iterates `common.fullDevices`, runs `exportV1` / `exportV2` / `exportV3`, then `export_dev()` for `api/v3/dev/**` and `export_v1_extras()` / `export_v2_extras()` for the two reference sites' auxiliary endpoints (see "V1 / V2 auxiliary files") plus `export_hub_extras()` for `api/v3/sitelog.json` / `api/v3/tools.json`, then invokes `app/web/scripts/generate-index.mjs` (Node.js) to regenerate `api/v3/index.json`, `api/v3/stats.json`, `api/v3/roms/*.json` and `api/v3/releases/*.json` |
| `migrate_logs_multilang.py` | Migrate the 21 `roms.logs_*` columns into the multilingual `logs` table plus a single language-neutral `roms.logs`; the old table is kept as `logs_legacy` |
| `resequence_ids.py` | Renumber `roms` / `dev` / `logs` ids into a dense sequence and reset their AUTO_INCREMENT counter; roms / dev sample 20 s to make sure nobody is writing and dump the old→new id map to `.backup/*_id_map_*.csv`; `logs` goes through `LogMaintenance.compact_ids` (transactional id shift + reference rewrite) and backs the table and references up to JSON first |
| `dedup_logs.py` | Dedup audit and merge for `logs`: merges groups that hold the same log, rewriting `roms.logs` / `dev.logs` references (masks unchanged, exports unaffected); `--apply` merges (auto backup), `--prune-unused` also removes orphan rows |
| `maintain_logs.py` | Unified `logs` maintenance entry point: `audit` (default, read-only) / `complete` (recompute the complete flag) / `prefix` (strip leading whitespace/punctuation from content/language columns, except `*`) / `content` (rebuild content from `logs_zh`) / `masks` (fill language masks, add-only) / `ids` (compact ids + rewrite references) / `unused` (prune orphan rows) / `auto-increment` / `merge` (explicit group merge; real translations win over English fallbacks) / `snapshot` (export snapshot) / `compare` (diff snapshots, detect content loss); dry-run unless `--apply` |
| `fix_mixed_translations.py` | Two-step `mixed_translations` repair: scan current rows or validated decisions; step 1 translates to English, finds similar rows and AI-compares them (merge on match); step 2 AI-clusters languages, creates new rows and routes refs by mask-language intersection, skipping ambiguous positions; read-only unless `--apply-merges` / `--apply-splits` |
| `restore_log_escapes.py` | Restore legacy JSON-storage escapes: `^`→`'`/`"`, `$$`→`%`; keeps `proofed` / `complete` / `lang_issues` by default, `--reset-flags` resets them; backup before `--apply` |
| `fill_missing_logs.py` | Find missing languages on `proofed=1` rows and AI-translate them back: estimate-only by default, `--run` preview, `--apply` writes (with backup); `--expected all\|owners`, `--langs`, `--min-confidence`; resets `proofed=0` unless `--keep-proofed` |
| `local_translate.py` | Local proofreading / filling with LM Studio Hunyuan-MT-7B: `check` verifies server and model; `fill` translates missing languages (`--apply` writes); `review` re-translates and compares (`--ratio` / `--short-ratio`, `--fix` replaces); `all` does both; prompts follow the official templates and outputs are validated for placeholders / prompt echo / target script; writes reuse `LogFiller.apply` (backup, `lang_issues` cleanup, `proofed=0`) |
| `fix_lang_issues.py` | Fix language columns from `logs.lang_issues`: default `correct` (replace with the AI `correct` translation; no correct/low confidence keeps the original); `--mode translate` AI-translates entries without `correct` and clears each fixed annotation; `--mode hybrid` clears only when no correct, `--mode clear` explicit deletion, `--mode move` to an empty correct column, `--clean-masks` drops mask bits; core columns require `--allow-core`; dry-run with backup |
| `proofread_logs.py` | Multilingual proofreading: `check --ids` audits specific logs.id (content untouched; marks proofed when ok); `scan` finds module-name conflicts by rules; `review` asks DeepSeek which Chinese module each row really maps to (only names present in that ROM, or null = extra module); `apply` renames or clears extra-module Chinese and updates mask bits, confidence-gated; `batch-review` audits all multilingual rows in batches (estimate only unless `--run`; ok rows are marked proofed); no content changes except the proofed flag |
| `import_dev_week.py` | Import developer (weekly) data into `dev` and backfill `roms.dev_week` (`--source hyperos\|nuxtmr\|miuiroms`, `--all`, `--weeks`, `--region`, `--dry-run`, `--backfill-roms`) |
| `import_sitelog.py` | Import the NuxtMR / HyperOS.fans site logs (`sitelog.json`) into the `sitelog` table (`--source nuxtmr\|hyperos`, `--all`, `--root`, `--dry-run`); it updates in place by unique key, so it is idempotent and burns no AUTO_INCREMENT ids |
| `import_hub_sitelog.py` | Derive hub's own changelogs (`hub.web` = `app/web`, `hub.admin` = `app/admin`) from git history and write them into the `sitelog` table: versions are numbered `V0.1.0`… by commit date; `--site`, `--drop-types chore,build,docs`, `--dry-run` |
| `migrate_v1v2_assets.py` | Seed the reference repositories' static endpoint files, device directories and "legacy devices that exist only in the reference repositories" into `api/v1` / `api/v2`; by default only missing files are added, `--force` overwrites static files (device files are never overwritten), and `--with-images` additionally copies the device images into `api/v2/assets/images` (skipped by default; the canonical location is `images/`) |
| `sync_devices.py` | Syncs the device list from `devices` / `roms` into `miroms/data.py` (`fullDevices`, `currentStable`, `flags`) |
| `fix_missing_tag_mappings.py` | Fixes missing device+tag mappings in `devices` (the V3 exporter matches branches by tag; missing ones lose ROMs); prints SQL to stdout or applies it directly with `--apply` |
| `common.py` | Backward-compat entry re-exporting the full public API of the `miroms` package, keeping module-level constants like `fullDevices`, `currentStable`, `flags` |
| `config.py` | DB connection config (host / port / user / password / database) + Cloudflare Pages deploy config (`api` base URL + `ids` list of site hooks; default: HUB / HyperOS.fans / MIUIer) + DeepSeek proofreading config (`deepseek_api_key` / `deepseek_model` / `deepseek_base_url` / `deepseek_reasoning_effort`; the key can also come from `DEEPSEEK_API_KEY`) + LM Studio local translation settings (`lmstudio_base_url` / `lmstudio_model` / `lmstudio_timeout`) |
| `push.py` | One-shot pipeline: run `exporter.py` → commit & push inside the `data` sub-repo (commit message = current datetime) → call `deploy.py` to deploy every site in `config.ids` (10 s pause between sites by default); exits non-zero if any deployment fails |
| `deploy.py` | Deploy only: POSTs `{config.api}/{id}` for each id in `config.ids` (Cloudflare Pages deploy hooks) and prints each site name, deploy ID / short_id / URL, waiting 10 s after each hook before triggering the next site (`--interval` overrides it, 0 = no wait); pass site names or hook-id prefixes to deploy a subset (e.g. `python3 scripts/deploy.py HUB`), `--list` only prints the targets; exit code 0 only if all succeed |
| `miroms/` | Core package: `constants.py` (constants, SDK versions, Android codenames, branch tables), `data.py` (device list), `database.py` (DB access + transactions), `network.py` / `crypto.py` / `firmware.py` (Xiaomi server fetch & decryption), `recorder.py` (data recording), `changelog.py` (changelogs), `logs_store.py` (multilingual log groups), `logs_text.py` (text predicates + traditional→simplified), `logs_maintenance.py` (dedup / reference rewrite / content consistency / language masks / id compaction / audit), `logs_proofread.py` (multilingual proofreading / AI review), `deepseek.py` (DeepSeek API client), `local_mt.py` (LM Studio local translation client + Hunyuan-MT prompts / output validation), `sitelog_store.py` (site-log persistence), `validator.py` (validation), `exporters.py` (V1/V2/V3 exporters), `legacy_exporters.py` (site auxiliary endpoint exports for api/v1 = NuxtMR, api/v2 = HyperOS.fans, api/v3 = hub's own site endpoints), `utils.py` (helpers) |

### Fetch / Deploy Scripts

| File | Description |
| --- | --- |
| `get_new_branch.py` | Fastboot + OTA probing to discover new branches / versions |
| `ota_former.py` | OTA version detection |
| `ota_full.py` | Full OTA offset probing |
| `xfu_full.py` | Local HTML verification |
| `get_current_fastboot.py` | Fetch current Fastboot package info |
| `mgc_fastboot.py` | Xiaomi community API fetch |
| `fetch_changelog.py` | Fetch multilingual changelogs and recovery packages; `--probe` reports which locales the API really translates, `--langs` selects locales, `--force` also stores English fallbacks, `--verify` checks and corrects existing logs against the official API (`--verify-only` / `--verify-limit` / `--max-id` for batching) |
| `aspatch.py` | Extract Android Security Patch dates |
| `test.py` | Debug / verification script (not part of the pipeline) |

The fetch scripts can also be run via VS Code Tasks (`.vscode/tasks.json` of the main repo, `Ctrl+Shift+B`).

### Pipeline

```
Xiaomi update server (update.miui.com)
        │  network / crypto / firmware fetch & decrypt
        ▼
MySQL database (miroms: devices / roms / logs / dev / branches / series)
        │  python3 scripts/sync_devices.py        → update miroms/data.py device list
        │  python3 scripts/fix_missing_tag_mappings.py --apply (when needed)
        │  python3 scripts/migrate_logs_multilang.py   → multilingual log groups (one-off)
        │  python3 scripts/import_dev_week.py --all    → developer weekly data (dev table)
        │  python3 scripts/exporter.py            → export api/v1|v2|v3 + dev + index.json / series.json
        ▼
JSON data (api/)
        │  python3 scripts/push.py (export → git commit & push → deploy every id in config.ids)
        ▼
Cloudflare Pages (deploy hooks) auto-deploy
        → api.miuier.com (CNAME, see the root CNAME file)
        → HUB / HyperOS.fans / MIUIer sites
```

---

## Conventions

### Version numbers

| System | Format | Example |
| --- | --- | --- |
| MIUI | `V<major>.<minor>.<patch>.<AndroidCode><ver><region>` | `V14.0.5.0.TKWTWXM` |
| HyperOS | `OS<major>.<minor>.<patch>.<AndroidCode><ver><region>` | `OS3.0.303.0.WOVCNXM` |

The trailing letters are **Android version code + version sequence + region tag**:

| Android version | Code letter |
| --- | --- |
| 13.0 | T |
| 14.0 | U |
| 15.0 | V |
| 16.0 | W |
| 17.0 | X |

Region tag examples: `CNXM` (Mainland China), `MIXM` (Global), `INXM` (India), `EAXM` (Europe EEA), `TWXM`
(Taiwan), `HKXM` (Hong Kong), `LMXM` (Latin America), etc.

### Branch fields

| Field | Meaning |
| --- | --- |
| `branch` / `btag` | Branch type: `F` = Stable, `X` = Developer; `branch` is the full tag (e.g. `CNTP`), `btag` the code letter |
| `zone` | Zone: `1` = China, `2` = International |
| `show` / `visibility` | Whether to show on the frontend: `1` = show, `0` = hide |
| `ep` | Enterprise edition: `1` = yes, `0` = no |
| `carrier` | Carrier list (JSON array), e.g. `["", "chinatelecom", "chinamobile", "chinaunicom"]` |
| `region` | Region code: `cn` (Mainland China) / `global` (Global) / `in` (India) / `eea` (Europe) / `tw` (Taiwan) / `hk` (Hong Kong) / `id` (Indonesia) / `ru` (Russia) / `mx` (Mexico) / `tr` (Turkey) / `lm` (Latin America) / `jp` (Japan) / `th` (Thailand) / `my` (Malaysia) / `sg` (Singapore) / `cl` (Chile) / `za` (South Africa) / `gt` (Guatemala), etc. |

### Package filenames

- **Recovery package**: `miui_<deviceName>Global_<version>_<10-char hash>_<Android version>.zip`
  e.g. `miui_AGATETWGlobal_OS1.0.15.0.UKWTWXM_04ec99268e_14.0.zip`
- **Fastboot package**: `<codename>_images_<version>_<date stamp>_<Android version>_<region>_<10-char hash>.tgz`
  e.g. `agate_tw_global_images_OS1.0.15.0.UKWTWXM_20250905.0000.00_14.0_tw_1615b6324d.tgz`

---

## Usage

The data files are plain JSON and can be consumed via GitHub Raw, CDN, or bundled into applications:

```bash
# Read device data directly (GitHub Raw)
curl -fsSL https://raw.githubusercontent.com/HegeKen/miroms/master/api/v3/devices/agate.json

# Or via the Cloudflare Pages site (CNAME: api.miuier.com; the site root is the repo root, data lives under /api)
curl -fsSL https://api.miuier.com/api/v3/devices/agate.json
```

The frontend site (`apiBaseUrl` is `https://api.miuier.com/api`), the admin panel, and mobile clients
(Android / iOS / mini-programs) all consume this repository; consumer code lives under `app/` in the main repo
[HegeKen/hub.miuier.com](https://github.com/HegeKen/hub.miuier.com).

---

## Related Docs

| Doc | 简体中文 | English |
| --- | --- | --- |
| Project overview | [../README.md](../README.md) | [../README_EN.md](../README_EN.md) |
| Frontend site | [../app/web/README.md](../app/web/README.md) | [../app/web/README_EN.md](../app/web/README_EN.md) |
| Admin panel | [../app/admin/README.md](../app/admin/README.md) | [../app/admin/README_EN.md](../app/admin/README_EN.md) |
| This data repo | [README.md](README.md) | [README_EN.md](README_EN.md) |

---

## Credits

The data pipeline in this repository relies on the runtimes, platforms and data sources below. Thanks to their authors and communities.

| Name | Purpose | License |
| --- | --- | --- |
| [Python 3](https://www.python.org/) | All fetch / export / deploy scripts in `scripts/` (stdlib only) | PSF-2.0 |
| [Node.js](https://nodejs.org/) | `../app/web/scripts/generate-index.mjs` builds the v3 indexes, yearly shards and `releases/*.json` | MIT |
| [MySQL](https://www.mysql.com/) | Data storage (InnoDB / utf8mb4; `devices` / `roms` / `branches` / `series`) | GPL-2.0 / commercial |
| [Cloudflare Pages](https://pages.cloudflare.com/) | Hosting for `api.miuier.com` and deploy-hook deployments | Cloudflare Terms of Service |
| [GitHub](https://github.com/) | Repository hosting, submodule and Raw distribution | GitHub Terms of Service |
| Xiaomi update servers (`update.miui.com`) | ROM versions, download URLs and changelogs (fetched and decrypted by `network` / `crypto` / `firmware`) | Data and trademarks owned by Xiaomi |
| Mi Community | Fastboot package information (`mgc_fastboot.py`) | Data and trademarks owned by Xiaomi |

> MIUI, HyperOS, Xiaomi, Redmi and POCO are trademarks of Xiaomi or its affiliates; this repository is not affiliated with Xiaomi.

---

## License

[Apache License 2.0](LICENSE)
