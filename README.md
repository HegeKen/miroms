# miroms · 小米 ROM 数据仓库

本仓库存储所有小米（Xiaomi / Redmi / POCO）设备的 ROM 数据，涵盖 **MIUI** 与 **HyperOS**（澎湃 OS）两代系统，包含正式版、开发版、运营商定制版、政企版等全部分支。

数据由 `scripts/` 下的 Python 管道从数据库（MySQL）自动生成，供 [hub.miuier.com](https://hub.miuier.com) 网站、管理后台及各客户端使用。

> This repository contains all Xiaomi ROM data (MIUI & HyperOS) for Xiaomi / Redmi / POCO devices, including Stable, Developer, Carrier and Enterprise editions. The data is generated automatically from a MySQL database by the scripts under `scripts/` and consumed by [hub.miuier.com](https://hub.miuier.com).

---

## 目录结构 / Repository Layout

```
.
├── api/                              # 导出的 JSON 数据（API 产物）
│   ├── v1/devices/<codename>.json    # V1：MIUI 设备数据（旧格式）
│   ├── v2/devices/<codename>.json    # V2：HyperOS 设备数据
│   ├── v3/devices/<codename>.json    # V3：全量设备数据（MIUI + HyperOS）
│   ├── v3/logs/<device>/[region/]<version>.json   # V3：中英文更新日志
│   ├── v3/index.json                 # V3：设备索引（设备列表 + 统计）
│   └── v3/stats.json                 # V3：近期更新统计
├── db_structure/                     # MySQL 表结构
│   ├── devices.sql                   #   设备表
│   ├── roms.sql                      #   ROM 表
│   └── branches.sql                  #   分支表
├── scripts/                          # 数据同步 / 导出脚本（Python）
│   ├── exporter.py                   #   主导出脚本
│   ├── sync_devices.py               #   同步设备列表
│   ├── fix_missing_tag_mappings.py   #   修复缺失 tag 映射
│   ├── common.py                     #   向后兼容入口（重新导出 miroms 包）
│   ├── config.py                     #   数据库连接配置
│   └── miroms/                       #   核心包（常量/工具/抓取/导出等）
├── fix_missing_tag_mappings.sql      # 生成的修复 SQL
├── LICENSE                           # Apache License 2.0
└── README.md
```

---

## API 数据 / API Data

### V1 — `api/v1/devices/<codename>.json`（仅 MIUI，旧格式）

每台设备一个文件，按分支（`branches`）组织，每个分支内 ROM 以 `links` 数组展开：

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

> V1 为旧版兼容格式，仅覆盖 MIUI 设备，新项目建议使用 V3。

### V2 — `api/v2/devices/<codename>.json`（HyperOS）

以版本号为 key 的 `roms` 字典 + `table` 表头描述：

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

### V3 — `api/v3/devices/<codename>.json`（全量，推荐）

同时覆盖 MIUI 与 HyperOS，新增 `tags` 嵌套字段与独立的更新日志文件：

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

### V3 附属文件

| 文件 | 说明 |
| --- | --- |
| `api/v3/logs/<device>/[region]/<version>.json` | 单个 ROM 的中英文更新日志，含区域时存放在 `region` 子目录，结构为 `{"logs_zh": {...}, "logs_en": {...}}` |
| `api/v3/index.json` | 设备索引：每台设备的名称、品牌、代码、Android 版本、支持的系统版本、分支数（`branchCount`）与 ROM 数（`romCount`） |
| `api/v3/stats.json` | 近期统计：`generatedAt` 生成时间、`recentDays` 统计天数、`recentRoms` 近期新增 ROM 数、`recent` 近期 ROM 明细列表 |

---

## 数据库结构 / Database Schema

数据库使用 MySQL（InnoDB，utf8mb4），表结构与字段含义见 `db_structure/`：

- **`devices.sql`** — 设备表：设备代号（`device`）、内部标识（`devtag`）、设备代码（`code`）、ROM 标签（`tag`）、区域（`region`）、运营商（`carrier`）、品牌（`brands` / `full_brands`）、中英文名（`full_names` / `names` / `xiaomi` / `redmi` / `poco`）、图片（`image`）、发布日期（`launch_date`）
- **`roms.sql`** — ROM 表：系统类型（`type`：MIUI / HyperOS）、大版本（`bigver`）、区域、标签、分支（`branch`：F=正式版 / X=开发版）、完整版本号（`version`）、Android 版本、发布日期（`beta_date` / `release_date` / `public_date`）、Recovery / Fastboot / 运营商定制包文件名（`recovery` / `fastboot` / `ctelecom` / `cmobile` / `cunicom` / `others`）、中英文更新日志（`logs_zh` / `logs_en`，JSON 格式）、安全补丁日期（`aspatch`）
- **`branches.sql`** — 分支表：分支类型、中英文名称、标签（`tag`）、代码后缀（`code`）、版本代码（`vercode`）、运营商、区域、分区（`zone`）、可见性（`visibility`）、是否政企版（`ep`）

---

## 数据脚本 / Scripts

`scripts/` 为纯 Python 3 实现（无第三方依赖），模块化结构如下：

| 文件 | 说明 |
| --- | --- |
| `exporter.py` | 入口脚本：遍历 `common.fullDevices` 依次执行 `exportV1` / `exportV2` / `exportV3`，完成后调用 `app/web/scripts/generate-index.mjs`（Node.js）重新生成 `api/v3/index.json` |
| `sync_devices.py` | 从 `devices` / `roms` 表同步设备列表到 `miroms/data.py`（`fullDevices`、`currentStable`、`flags`） |
| `fix_missing_tag_mappings.py` | 修复 `devices` 表中缺失的 device+tag 映射（V3 导出器按 tag 匹配分支，缺失会导致 ROM 丢失），输出 SQL 到 stdout 或 `--apply` 直接执行 |
| `common.py` | 向后兼容入口，重新导出 `miroms` 包全部公共 API，并保留 `fullDevices`、`currentStable`、`flags` 等模块级常量 |
| `config.py` | 数据库连接配置（host / port / user / password / database） |
| `miroms/` | 核心包：`constants.py`（常量、SDK 版本、Android 代号、分支表）、`data.py`（设备列表）、`database.py`（数据库访问）、`network.py` / `crypto.py` / `firmware.py`（小米服务器抓取与解密）、`recorder.py`（数据录入）、`changelog.py`（更新日志）、`validator.py`（校验）、`exporters.py`（V1/V2/V3 导出器）、`utils.py`（工具函数） |

### 生成流程 / Pipeline

```
小米更新服务器 (update.miui.com)
        │  network / crypto / firmware 抓取并解密
        ▼
MySQL 数据库 (miroms: devices / roms / branches)
        │  python3 scripts/sync_devices.py        → 更新 miroms/data.py 设备列表
        │  python3 scripts/fix_missing_tag_mappings.py --apply（必要时）
        │  python3 scripts/exporter.py            → 导出 api/v1|v2|v3 + index.json
        ▼
JSON 数据（api/）
        │  git commit & push
        ▼
Cloudflare Pages（deploy hook）自动部署 → hub.miuier.com
```

---

## 字段约定 / Conventions

### 版本号

| 系统 | 版本格式 | 示例 |
| --- | --- | --- |
| MIUI | `V<major>.<minor>.<patch>.<AndroidCode><ver><region>` | `V14.0.5.0.TKWTWXM` |
| HyperOS | `OS<major>.<minor>.<patch>.<AndroidCode><ver><region>` | `OS3.0.303.0.WOVCNXM` |

版本尾部的字母依次为 **Android 版本代号 + 版本序号 + 区域标签**：

| Android 版本 | 代号字母 |
| --- | --- |
| 13.0 | T |
| 14.0 | U |
| 15.0 | V |
| 16.0 | W |
| 17.0 | X |

区域标签示例：`CNXM`（中国大陆）、`MIXM`（全球）、`INXM`（印度）、`EAXM`（欧洲 EEA）、`TWXM`（中国台湾）、`HKXM`（中国香港）、`LMXM`（拉丁美洲）等。

### 分支字段

| 字段 | 含义 |
| --- | --- |
| `branch` / `btag` | 分支类型：`F` = 正式版（Stable），`X` = 开发版（Developer）；`branch` 为完整标签（如 `CNTP`），`btag` 为对应代号 |
| `zone` | 区域分区：`1` = 中国，`2` = 国际 |
| `show` / `visibility` | 是否在前端展示：`1` = 显示，`0` = 隐藏 |
| `ep` | 是否政企版（Enterprise）：`1` = 是，`0` = 否 |
| `carrier` | 运营商列表（JSON 数组），如 `["", "chinatelecom", "chinamobile", "chinaunicom"]` |
| `region` | 区域代号：`cn`（中国大陆）/ `global`（全球）/ `in`（印度）/ `eea`（欧洲）/ `tw`（中国台湾）/ `hk`（中国香港）/ `id`（印尼）/ `ru`（俄罗斯）/ `mx`（墨西哥）/ `tr`（土耳其）/ `lm`（拉美）/ `jp`（日本）/ `th`（泰国）/ `my`（马来西亚）/ `sg`（新加坡）/ `cl`（智利）/ `za`（南非）/ `gt`（危地马拉）等 |

### 安装包文件名

- **Recovery 包**：`miui_<设备名>Global_<版本号>_<10位哈希>_<Android版本>.zip`
  例：`miui_AGATETWGlobal_OS1.0.15.0.UKWTWXM_04ec99268e_14.0.zip`
- **Fastboot 包**：`<设备代号>_images_<版本号>_<日期戳>_<Android版本>_<区域>_<10位哈希>.tgz`
  例：`agate_tw_global_images_OS1.0.15.0.UKWTWXM_20250905.0000.00_14.0_tw_1615b6324d.tgz`

---

## 使用方式 / Usage

数据文件为纯 JSON，可直接通过 GitHub Raw、CDN 或打包进应用使用：

```bash
# 直接读取设备数据
curl -fsSL https://raw.githubusercontent.com/HegeKen/miroms/master/api/v3/devices/agate.json
```

前端站点、管理后台与移动端（Android / iOS / 小程序）均为本仓库数据的消费者；各消费者代码见主仓库 [HegeKen/hub.miuier.com](https://github.com/HegeKen/hub.miuier.com) 的 `app/` 目录。

---

## License

[Apache License 2.0](LICENSE)
