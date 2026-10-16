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
│   ├── resequence_ids.py             #   renumber roms / dev ids (remove AUTO_INCREMENT gaps)
│   ├── rebuild_roms_logs.py          #   rebuild roms.logs from the backup DB (fix dangling references)
│   ├── import_dev_week.py            #   import dev (weekly) data into dev table
│   ├── import_sitelog.py             #   import both sites' site logs into the sitelog table
│   ├── import_hub_sitelog.py         #   import hub's own (web / admin) changelog from git history
│   ├── migrate_v1v2_assets.py        #   seed v1/v2 static files / device dirs / legacy devices
│   ├── sync_devices.py               #   sync device list
│   ├── fix_missing_tag_mappings.py   #   fix missing tag mappings
│   ├── common.py                     #   backward-compat entry (re-exports the miroms package)
│   ├── config.py                     #   DB connection config + deploy hook
│   ├── push.py                       #   one-shot export → commit & push → deploy
│   ├── deploy.py                     #   trigger Cloudflare Pages deploy
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
| `api/v1/weekly.json` | Weekly index: `latest` / `oldest` / `versions[{version, period, weeks}]`. Weeks come from the `dev` table (`region='cn'`, `show=1` MIUI weeks), and `oldest` is the first week that has a V1 single-week detail page (`source='nuxtmr'`, week 560); earlier weeks still appear in `versions` and the frontend links out to old.miuier.com |
| `api/v1/weekly/week-<week>-cn.json` | One week: announcement (`zh-cn` / `en-us` / `CnComID`, etc.) + `devices` list + `tpd` suspended builds + `addons` upgrade notes / release notes + `logs` module logs; the data comes from `dev` (`source='nuxtmr'`) and `roms.dev_week` |
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
python3 scripts/resequence_ids.py --apply         # renumber roms and reset the counter
python3 scripts/resequence_ids.py --verify        # verify density only
```

#### Log deduplication (always verified)

`logs` rows are shared across ROMs, and the write path matches by **"same type + no language conflict"**:
before writing, the whole `logs` table is loaded into an in-memory row pool (`LogStore.load_index`) and an
existing group is reused whenever its language texts do not conflict — so the same log is recognised even when
the primary content differs (`#25 content=相册` vs `#27 content=Gallery`), unlike the early implementation that
only looked rows up by `content_hash`.

Three independent guards now report duplicates and fail loudly:

| Where | What |
| --- | --- |
| `python3 scripts/dedup_logs.py` | Lists mergeable groups; `--apply` merges, `--prune-unused` removes orphan rows |
| `python3 scripts/resequence_ids.py` | Renumber `roms` / `dev` ids into a dense sequence and reset their AUTO_INCREMENT counter; samples 20 s to make sure nobody is writing and dumps the old→new id map to `.backup/*_id_map_*.csv`. `logs.id` is referenced by `roms.logs` / `dev.logs`, so it is deliberately not allowed |
| `import_dev_week.py` / `migrate_logs_multilang.py` | Call `LogStore.duplicate_report()` at the end and exit non-zero when duplicates are found |
| Admin `/logs` page → "dedup audit" | `GET /api/logs/audit`: duplicate groups, duplicate rows, unreferenced rows |

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
  primary text with Chinese first, `content_hash`, plus 21 `logs_xx` language columns)
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
| `import_dev_week.py` | Import developer (weekly) data into `dev` and backfill `roms.dev_week` (`--source hyperos\|nuxtmr\|miuiroms`, `--all`, `--weeks`, `--region`, `--dry-run`, `--backfill-roms`) |
| `import_sitelog.py` | Import the NuxtMR / HyperOS.fans site logs (`sitelog.json`) into the `sitelog` table (`--source nuxtmr\|hyperos`, `--all`, `--root`, `--dry-run`); it updates in place by unique key, so it is idempotent and burns no AUTO_INCREMENT ids |
| `import_hub_sitelog.py` | Derive hub's own changelogs (`hub.web` = `app/web`, `hub.admin` = `app/admin`) from git history and write them into the `sitelog` table: versions are numbered `V0.1.0`… by commit date; `--site`, `--drop-types chore,build,docs`, `--dry-run` |
| `migrate_v1v2_assets.py` | Seed the reference repositories' static endpoint files, device directories and "legacy devices that exist only in the reference repositories" into `api/v1` / `api/v2`; by default only missing files are added, `--force` overwrites static files (device files are never overwritten), and `--with-images` additionally copies the device images into `api/v2/assets/images` (skipped by default; the canonical location is `images/`) |
| `sync_devices.py` | Syncs the device list from `devices` / `roms` into `miroms/data.py` (`fullDevices`, `currentStable`, `flags`) |
| `fix_missing_tag_mappings.py` | Fixes missing device+tag mappings in `devices` (the V3 exporter matches branches by tag; missing ones lose ROMs); prints SQL to stdout or applies it directly with `--apply` |
| `common.py` | Backward-compat entry re-exporting the full public API of the `miroms` package, keeping module-level constants like `fullDevices`, `currentStable`, `flags` |
| `config.py` | DB connection config (host / port / user / password / database) + Cloudflare Pages deploy hook (`deploy_url`) |
| `push.py` | One-shot pipeline: run `exporter.py` → commit & push inside the `data` sub-repo (commit message = current datetime) → call `deploy.py` to trigger deployment |
| `deploy.py` | Deploy only: POSTs `config.deploy_url` (Cloudflare Pages deploy hook) and prints the deploy ID |
| `miroms/` | Core package: `constants.py` (constants, SDK versions, Android codenames, branch tables), `data.py` (device list), `database.py` (DB access), `network.py` / `crypto.py` / `firmware.py` (Xiaomi server fetch & decryption), `recorder.py` (data recording), `changelog.py` (changelogs), `sitelog_store.py` (site-log persistence), `validator.py` (validation), `exporters.py` (V1/V2/V3 exporters), `legacy_exporters.py` (site auxiliary endpoint exports for api/v1 = NuxtMR, api/v2 = HyperOS.fans, api/v3 = hub's own site endpoints), `utils.py` (helpers) |

### Fetch / Deploy Scripts

| File | Description |
| --- | --- |
| `get_new_branch.py` | Fastboot + OTA probing to discover new branches / versions |
| `ota_former.py` | OTA version detection |
| `ota_full.py` | Full OTA offset probing |
| `xfu_full.py` | Local HTML verification |
| `get_current_fastboot.py` | Fetch current Fastboot package info |
| `mgc_fastboot.py` | Xiaomi community API fetch |
| `fetch_changelog.py` | Fetch multilingual changelogs and recovery packages; `--probe` reports which locales the API really translates, `--langs` selects locales, `--force` also stores English fallbacks |
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
        │  python3 scripts/push.py (export → git commit & push → trigger deploy)
        ▼
Cloudflare Pages (deploy hook) auto-deploy → api.miuier.com (CNAME, see the root CNAME file)
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
