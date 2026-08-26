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
│   ├── v3/logs/<device>/[region/]<version>.json   # V3: zh/en changelogs
│   ├── v3/roms/<OS>.json             # V3: ROM lists grouped by OS (OS1/OS2/OS3…)
│   ├── v3/index.json                 # V3: device index (device list + stats)
│   ├── v3/series.json                # V3: series data (exported from the series table)
│   └── v3/stats.json                 # V3: recent-update stats
├── db_structure/                     # MySQL table schemas
│   ├── devices.sql                   #   devices table
│   ├── roms.sql                      #   roms table
│   ├── branches.sql                  #   branches table
│   └── series.sql                    #   series table
├── scripts/                          # sync / fetch / export / deploy scripts (Python)
│   ├── exporter.py                   #   main export script
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
| `api/v3/logs/<device>/[region]/<version>.json` | zh/en changelog for a single ROM; region-tagged versions live in a `region` subdirectory. Structure: `{"logs_zh": {...}, "logs_en": {...}}` |
| `api/v3/roms/<OS>.json` | ROM lists grouped by OS major version (e.g. `OS1.json` = HyperOS 1); each entry has device, version, Android, region, branch name, dates and package filenames — combine by version to build per-device ROM tables |
| `api/v3/index.json` | Device index: name, brand, series (`series`), code, Android versions, supported systems, branch count (`branchCount`) and ROM count (`romCount`) per device |
| `api/v3/series.json` | Series: series list (brand, zh/en names, `device_ids` membership) plus device ordering (`order`) |
| `api/v3/stats.json` | Recent stats: `generatedAt` generation time, `recentDays` window, `recentRoms` recent additions count, `recent` recent ROM detail list |

---

## Database Schema

MySQL (InnoDB, utf8mb4); table structure and field meanings are in `db_structure/`:

- **`devices.sql`** — devices: codename (`device`), internal id (`devtag`), device code (`code`), ROM tag (`tag`),
  region (`region`), carrier (`carrier`), brands (`brands` / `full_brands`), zh/en names (`full_names` / `names` /
  `xiaomi` / `redmi` / `poco`), image (`image`), launch date (`launch_date`)
- **`roms.sql`** — ROMs: system type (`type`: MIUI / HyperOS), major version (`bigver`), region, tag, branch
  (`branch`: F=Stable / X=Developer), full version (`version`), Android version, release dates (`beta_date` /
  `release_date` / `public_date`), Recovery / Fastboot / carrier package filenames (`recovery` / `fastboot` /
  `ctelecom` / `cmobile` / `cunicom` / `others`), zh/en changelogs (`logs_zh` / `logs_en`, JSON), security patch
  date (`aspatch`)
- **`branches.sql`** — branches: branch type, zh/en names, tag (`tag`), code suffix (`code`), version code
  (`vercode`), carrier, region, zone (`zone`), visibility (`visibility`), enterprise flag (`ep`)
- **`series.sql`** — series: brand (`brand`: xiaomi / redmi / poco), zh/en names (`name_zh` / `name_en`), device
  membership (`device_ids`, JSON array), ordering (`sort_order`)

---

## Scripts

`scripts/` is pure Python 3 (no third-party dependencies), modular structure:

| File | Description |
| --- | --- |
| `exporter.py` | Entry script: iterates `common.fullDevices`, runs `exportV1` / `exportV2` / `exportV3`, then invokes `app/web/scripts/generate-index.mjs` (Node.js) to regenerate `api/v3/index.json` |
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
| `fetch_changelog.py` | Fetch changelogs and recovery packages |
| `aspatch.py` | Extract Android Security Patch dates |
| `test.py` | Debug / verification script (not part of the pipeline) |

The fetch scripts can also be run via VS Code Tasks (`.vscode/tasks.json` of the main repo, `Ctrl+Shift+B`).

### Pipeline

```
Xiaomi update server (update.miui.com)
        │  network / crypto / firmware fetch & decrypt
        ▼
MySQL database (miroms: devices / roms / branches / series)
        │  python3 scripts/sync_devices.py        → update miroms/data.py device list
        │  python3 scripts/fix_missing_tag_mappings.py --apply (when needed)
        │  python3 scripts/exporter.py            → export api/v1|v2|v3 + index.json / series.json
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

## License

[Apache License 2.0](LICENSE)
