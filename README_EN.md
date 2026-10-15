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
│   ├── v1/devices/<codename>.json    # V1: MIUI device data (legacy format)
│   ├── v2/devices/<codename>.json    # V2: HyperOS device data
│   ├── v3/devices/<codename>.json    # V3: full device data (MIUI + HyperOS)
│   ├── v3/logs/<device>/[region/]<version>.json   # V3: multilingual changelogs
│   ├── v3/dev/index.json             # V3: developer (weekly) release index
│   ├── v3/dev/<region>/<week>.json   # V3: one dev week (announcement + devices + logs)
│   ├── v3/roms/<OS>.json             # V3: ROM lists grouped by OS (OS1/OS2/OS3…)
│   ├── v3/releases/<year>.json       # V3: ROM lists grouped by release date (year shards)
│   ├── v3/releases/index.json        # V3: release index metadata (date range / per-year stats)
│   ├── v3/index.json                 # V3: device index (device list + stats)
│   ├── v3/series.json                # V3: series data (exported from the series table)
│   └── v3/stats.json                 # V3: recent-update stats
├── db_structure/                     # MySQL table schemas (incl. logs.sql / dev.sql)
│   ├── devices.sql                   #   devices table
│   ├── roms.sql                      #   roms table
│   ├── branches.sql                  #   branches table
│   └── series.sql                    #   series table
├── scripts/                          # sync / fetch / export / deploy scripts (Python)
│   ├── exporter.py                   #   main export script
│   ├── migrate_logs_multilang.py     #   logs table rebuild + roms.logs migration
│   ├── import_dev_week.py            #   import dev (weekly) data into dev table
│   ├── sync_devices.py               #   sync device list
│   ├── fix_missing_tag_mappings.py   #   fix missing tag mappings
│   ├── common.py                     #   backward-compat entry (re-exports the miroms package)
│   ├── config.py                     #   DB connection config + deploy hook
│   ├── push.py                       #   one-shot export → commit & push → deploy
│   ├── deploy.py                     #   trigger Cloudflare Pages deploy
│   ├── *.py                          #   various fetch scripts (see "Fetch / Deploy Scripts")
│   └── miroms/                       #   core package (constants/utils/fetch/export, etc.)
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

### Multilingual changelogs

Changelogs come from `update.miui.com`: the `l` field in the request form selects the language, and locales Xiaomi has no translation for fall back to English. Use `--probe` first to confirm which locale the API actually honours — Arabic, for example, is only translated for `ar_EG`; `ar` / `ar_SA` / `ar_AE` all fall back to English. Workflow:

1. Register the locale in `CHANGELOG_LOCALES` (`scripts/miroms/constants.py`: column / API locale / site locale)
2. Add the matching column to the `logs` table (schema: `db_structure/logs.sql`; the column set follows `CHANGELOG_LOCALES` automatically — the `roms` table no longer needs to change)
3. `python3 scripts/fetch_changelog.py --probe 5` to see which locales actually return a distinct translation (no writes)
4. `python3 scripts/fetch_changelog.py --langs ja,ko,ru` to fill specific locales; without arguments every locale is processed in order
Processing is batched by ROM id: each locale first collects its own array of pending ids, then the union of ids is walked once — a ROM's row is queried once and its request form is built once, so a ROM present in several locales only swaps the `l` parameter for each extra request and is removed from those arrays right after, avoiding duplicate queries and duplicate requests.

Writes are per-row `UPDATE`s on an `autocommit` connection, so each one lands immediately (nothing is batched into a final commit). On startup the script prints the database it actually connects to and verifies that every locale column exists — a missing column aborts with the migration command instead of being swallowed silently; failed writes are counted as `write_failed` and the first error is printed, so it can no longer report "N written" while the table stays untouched. When nothing was written the script lists the likely causes: the API fell back to English for every locale (check with `--probe`, or force with `--force`), the pending arrays are empty (`--min-id` too high), or the database rejected the writes. `--dry-run` shows what would be written without touching the DB.

Locales that fall back to English are skipped automatically (column stays NULL) so the table does not fill with English copies; use `--force` to store them anyway.

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

---

## Scripts

`scripts/` is pure Python 3 (no third-party dependencies), modular structure:

| File | Description |
| --- | --- |
| `exporter.py` | Entry script: iterates `common.fullDevices`, runs `exportV1` / `exportV2` / `exportV3`, then `export_dev()` for `api/v3/dev/**`, then invokes `app/web/scripts/generate-index.mjs` (Node.js) to regenerate `api/v3/index.json`, `api/v3/stats.json`, `api/v3/roms/*.json` and `api/v3/releases/*.json` |
| `migrate_logs_multilang.py` | Migrate the 21 `roms.logs_*` columns into the multilingual `logs` table plus a single language-neutral `roms.logs`; the old table is kept as `logs_legacy` |
| `import_dev_week.py` | Import developer (weekly) data into `dev` and backfill `roms.dev_week` (`--source hyperos\|nuxtmr\|miuiroms`, `--all`, `--weeks`, `--region`, `--dry-run`, `--backfill-roms`) |
| `sync_devices.py` | Syncs the device list from `devices` / `roms` into `miroms/data.py` (`fullDevices`, `currentStable`, `flags`) |
| `fix_missing_tag_mappings.py` | Fixes missing device+tag mappings in `devices` (the V3 exporter matches branches by tag; missing ones lose ROMs); prints SQL to stdout or applies it directly with `--apply` |
| `common.py` | Backward-compat entry re-exporting the full public API of the `miroms` package, keeping module-level constants like `fullDevices`, `currentStable`, `flags` |
| `config.py` | DB connection config (host / port / user / password / database) + Cloudflare Pages deploy hook (`deploy_url`) |
| `push.py` | One-shot pipeline: run `exporter.py` → commit & push inside the `data` sub-repo (commit message = current datetime) → call `deploy.py` to trigger deployment |
| `deploy.py` | Deploy only: POSTs `config.deploy_url` (Cloudflare Pages deploy hook) and prints the deploy ID |
| `miroms/` | Core package: `constants.py` (constants, SDK versions, Android codenames, branch tables), `data.py` (device list), `database.py` (DB access), `network.py` / `crypto.py` / `firmware.py` (Xiaomi server fetch & decryption), `recorder.py` (data recording), `changelog.py` (changelogs), `validator.py` (validation), `exporters.py` (V1/V2/V3 exporters), `utils.py` (helpers) |

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

# Or via the Cloudflare Pages site (CNAME: api.miuier.com)
curl -fsSL https://api.miuier.com/v3/devices/agate.json
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
