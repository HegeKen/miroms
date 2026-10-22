# miroms · 小米 ROM 数据仓库

本仓库存储所有小米（Xiaomi / Redmi / POCO）设备的 ROM 数据，涵盖 **MIUI** 与 **HyperOS**（澎湃 OS）两代系统，包含正式版、开发版、运营商定制版、政企版等全部分支。

数据由 `scripts/` 下的 Python 管道从数据库（MySQL）自动生成，供 [hub.miuier.com](https://hub.miuier.com) 网站、管理后台及各客户端使用。

> This repository contains all Xiaomi ROM data (MIUI & HyperOS) for Xiaomi / Redmi / POCO devices, including Stable, Developer, Carrier and Enterprise editions. The data is generated automatically from a MySQL database by the scripts under `scripts/` and consumed by [hub.miuier.com](https://hub.miuier.com).

> 🌐 **简体中文:** [README.md](README.md) · **English:** [README_EN.md](README_EN.md)

---

## 目录结构 / Repository Layout

```
.
├── api/                              # 导出的 JSON 数据（API 产物）
│   ├── v1/devices/<codename>.json    # V1：MIUI 设备数据（旧格式，NuxtMR 站点）
│   ├── v1/index.json                 # V1：首页「本周正式版更新」
│   ├── v1/weekly.json                # V1：周更大版本 -> 周数索引
│   ├── v1/weekly/week-<week>-cn.json # V1：单周公告 + 机型清单 + 更新日志
│   ├── v1/devlist.json               # V1：机型列表目录（含 android / miui）
│   ├── v1/sitelog.json               # V1：站点日志（sitelog 表 site=nuxtmr）
│   ├── v1/*.json                     # V1：遗留 / 手写接口（见「V1 / V2 附属文件」）
│   ├── v2/devices/<codename>.json    # V2：HyperOS 设备数据（HyperOS.fans 站点）
│   ├── v2/index.json                 # V2：首页「近 6 天新增」
│   ├── v2/dev.json                   # V2：开发版大版本 -> 周数索引
│   ├── v2/dev/<week>.json            # V2：单周公告 + ROM 清单 + 多语言日志
│   ├── v2/devices.json               # V2：机型列表目录（含 supports / android）
│   ├── v2/sitelog.json               # V2：站点日志（sitelog 表 site=hyperos.fans）
│   ├── v2/*.json                     # V2：遗留 / 手写接口（见「V1 / V2 附属文件」）
│   ├── v3/devices/<codename>.json    # V3：全量设备数据（MIUI + HyperOS）
│   ├── v3/logs/<device>/[region/]<version>.json   # V3：多语言更新日志
│   ├── v3/dev/index.json             # V3：开发版（周更）周次索引
│   ├── v3/dev/<region>/<week>.json   # V3：开发版单周公告 + 机型清单 + 多语言日志
│   ├── v3/roms/<OS>.json             # V3：按系统版本（OS1/OS2/OS3…）分组的 ROM 列表
│   ├── v3/releases/<year>.json       # V3：按发布日期分组的 ROM 列表（按年份分片）
│   ├── v3/releases/index.json        # V3：发布日期索引的元信息（日期范围 / 年份统计）
│   ├── v3/index.json                 # V3：设备索引（设备列表 + 统计）
│   ├── v3/series.json                # V3：机型系列数据（series 表导出）
│   ├── v3/stats.json                 # V3：近期更新统计
│   ├── v3/sitelog.json               # V3：hub 自身站点日志（hub.web / hub.admin）
│   └── v3/tools.json                 # V3：刷机工具下载（由 v1/tools.json 转换）
├── db_structure/                     # MySQL 表结构
│   ├── devices.sql                   #   设备表
│   ├── roms.sql                      #   ROM 表
│   ├── logs.sql                      #   更新日志表（同一日志多语言共用一行）
│   ├── dev.sql                       #   开发版（周更）表
│   ├── branches.sql                  #   分支表
│   ├── series.sql                    #   机型系列表
│   ├── sitelog.sql                   #   站点日志表（site 列区分 nuxtmr / hyperos.fans / hub.web / hub.admin）
│   └── migrations/                   #   schema 迁移 SQL
├── scripts/                          # 数据同步 / 抓取 / 导出 / 部署脚本（Python）
│   ├── exporter.py                   #   主导出脚本（v1 / v2 / v3 + 站点附属接口）
│   ├── migrate_logs_multilang.py     #   日志多语言分组迁移（logs 重建 + roms.logs 回写）
│   ├── dedup_logs.py                 #   logs 去重体检 / 合并重复分组 / 清理孤儿行
│   ├── maintain_logs.py              #   logs 统一维护：体检 / content / 掩码 / id / 孤儿行 / 计数器
│   ├── proofread_logs.py             #   日志多语言校对：规则扫描 + DeepSeek 复核 + 安全写回
│   ├── fix_lang_issues.py            #   按 logs.lang_issues 修正错误语言列 / 清理掩码位
│   ├── fill_missing_logs.py         #   proofed 行缺失语言 AI 翻译回填
│   ├── local_translate.py           #   LM Studio（Hunyuan-MT-7B）逐条校对 / 补写翻译
│   ├── restore_log_escapes.py       #   还原旧 JSON 转义 ^ / $$（一次性）
│   ├── fix_mixed_translations.py    #   mixed_translations 两步修复（规划 / merge / split）
│   ├── resequence_ids.py             #   重排 roms / dev / logs 的 id（消除自增空档）
│   ├── rebuild_roms_logs.py          #   按备份库重建 roms.logs（修复悬空引用）
│   ├── import_dev_week.py            #   导入开发版周更数据（dev 表 + roms.dev_week）
│   ├── import_sitelog.py             #   导入两个站点的站点日志到 sitelog 表
│   ├── import_hub_sitelog.py         #   按 git 记录导入 hub 自身（web / admin）的更新日志
│   ├── migrate_v1v2_assets.py        #   补齐 v1/v2 的静态文件 / 机型目录 / 图片 / 遗留机型
│   ├── sync_devices.py               #   同步设备列表
│   ├── fix_missing_tag_mappings.py   #   修复缺失 tag 映射
│   ├── common.py                     #   向后兼容入口（重新导出 miroms 包）
│   ├── config.py                     #   数据库连接配置 + 部署配置（api + ids）
│   ├── push.py                       #   一键导出 → 提交推送 → 依次部署全部站点
│   ├── deploy.py                     #   按 config.ids 逐个触发 Cloudflare Pages 部署
│   ├── *.py                          #   各类抓取脚本（见下文「抓取 / 部署脚本」）
│   └── miroms/                       #   核心包（常量/工具/抓取/导出等）
│       ├── exporters.py              #     exportV1 / exportV2 / exportV3 / export_dev
│       └── legacy_exporters.py       #     v1 / v2 站点附属接口导出
├── CNAME                             # Github Pages 域名（api.miuier.com）
├── fix_missing_tag_mappings.sql      # 生成的修复 SQL
├── new_flags.txt / new_roms.txt      # 抓取过程的临时产物（可忽略）
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

### V1 / V2 附属文件（NuxtMR / HyperOS.fans 站点接口）

两个参考站点原先各自维护一份数据仓库（NuxtMR 的 `public/MRData/data`、
HyperOS.fans 的 `public/data`），除设备文件外还有一批站点级接口。迁移到本仓库后：

* **从库里重生成**（`scripts/exporter.py` → `miroms/legacy_exporters.py`）：

| 文件 | 说明 |
| --- | --- |
| `api/v1/index.json` | 首页「本周正式版更新」：按 ISO 周聚合 `roms`（`type=MIUI`、`branch=F`，排除 `.EP.` 政企版），字段 `year` / `week` / `period` / `nextperiod` / `date` / `stable[{code, zh-cn, en-us, date, rom}]`，同一机型当周多个分支版本以 `"; "` 连接 |
| `api/v1/weekly.json` | 周更索引：`latest` / `oldest` / `versions[{version, period, weeks}]`。周次来自 `dev` 表（`region='cn'`、`show=1` 的全部 MIUI 周，不区分来源 miuiroms / nuxtmr），`oldest` 即最早一周，所有周次都有 V1 单周详情页 |
| `api/v1/weekly/week-<week>-cn.json` | 单周公告（`zh-cn` / `en-us` / `CnComID` 等）+ `devices` 机型清单 + `tpd` 停版 + `addons` 升级说明 / 版本说明 + `logs` 模块日志；数据来自 `dev`（`bigver` 为 MIUI 的全部周次，不限来源）与 `roms.dev_week` |
| `api/v1/devlist.json` | 机型列表页 / sitemap 的设备目录：品牌 → 系列 → 机型（人工维护顺序），脚本按 `devices/<code>.json` 回填 `android` / `miui` |
| `api/v1/sitelog.json` | 站点日志，结构 `{"log": [{sudate, ver, zh-cn, en-us, log: [{zh-cn, en-us}]}]}`，来自 `sitelog` 表 `site='nuxtmr'` |
| `api/v2/index.json` | 首页「近 6 天新增」：按 `roms.insdate` 聚合 HyperOS ROM（窗口 6 天，与源站点一致），结构 `{"recent": {time, developing, roms: {<device>: {name, versions: [{insert_date, version}]}}}}` |
| `api/v2/dev.json` | 开发版索引：`{"HyperOS": [{bigVer, start, latest, weeks}]}`，`bigVer` 由 `dev.bigver`（`HyperOS 1`）转成站点写法（`HyperOS1.0`），周次来自 `dev`（`source='hyperos.fans'`） |
| `api/v2/dev/<week>.json` | 单周公告（`title` / `postId` / `update` / `versions` / `description` / `attention` / `show`）+ `roms` ROM 清单 + `suspended` 停版 + 多语言 `logs`（`[{module: {zh, en}, log: [{zh, en}]}]`） |
| `api/v2/devices.json` | 机型列表页 / sitemap 的目录：`mi` / `redmi` / `poco` → 机型（人工维护 `image` / `series`），脚本按 `devices/<code>.json` 回填 `supports` / `android` |
| `api/v2/sitelog.json` | 站点日志，结构 `{"icons": [...], "logs": [{siteVer, icon, date, log: [{zh, en}]}]}`，来自 `sitelog` 表 `site='hyperos.fans'`（`icons` 调色板取 `kind='meta'` 行） |

* **随仓库维护**（库里没有来源，`scripts/migrate_v1v2_assets.py` 只负责首次播种，之后不再自动生成）：
  * 手写内容：`api/v1/tools.json`、`api/v1/thanks.json`、`api/v1/devices.json`、`api/v2/updates.json`、`api/v2/new-rom.json`
  * 废弃脚本的归档产物（字段大面积为空，保留仅为兼容旧客户端）：`api/v1/log.json`、`api/v1/stable.json`、`api/v1/update.json`、`api/v1/update_full.json`、`api/v1/newrom.json`
  * 机型图片：**不搬运**——规范位置是仓库根的 `images/`（站点根 `https://api.miuier.com/images/<file>`，前端 `buildDeviceImageUrl()` 即走这里）。参考站点的 `assets/images/**` 与它逐文件一致（382/382，且 `api/v2/devices.json` 引用的 247 张全覆盖），再复制一份到 `api/v2/assets/images/**` 属于纯重复（约 25 MB）；`migrate_v1v2_assets.py --with-images` 可按需还原。
  * 仅存于参考仓库、`miroms` 库中没有记录的遗留机型（`devices/<codename>.json`）：
    V1 的 `HM2013023` / `HM2014011` / `HM2014501` / `camellian` / `cannong` / `ido` / `laurel` / `lcsh92` / `lcsh92_wet_tdd` / `mione` / `pond`，
    V2 的 `arctic` / `chicago` / `coral` / `donghai` / `moscow` / `pissarro_in` / `pond` / `suiren` / `yupei_d`

> 迁移自参考仓库的已知差异（都源于「以库为准」的重生成，属预期）：
> 机型名取自 `devices.full_names`（可能同时包含 POCO 等马甲名，如 `blue` = 「POCO C61 / Redmi A3」）；
> `dev.bigver` 统一为 `MIUI V6`（V1 周更索引里按历史写法映射回 `MIUI 6`）；
> V1 周更列表会包含库里 `dev_week` 已绑定但源文件未列出的机型，并去掉源文件里完全重复的行；
> 周更日志的英文以 `logs` 表里的官方译文为准（源文件是人工翻译）；
> V1 周更公告里 `no`（手写机型简称，源文件 54 周中有 30 周带此字段）、`vid`、`showdevices` 与 `CnBBSID` / `GbBBSID`（源文件里始终为空）在库里没有对应字段，导出统一为空串 / `"1"`——这些字段前端目前都没有使用。

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
| `api/v3/logs/<device>/[region]/<version>.json` | 单个 ROM 的多语言更新日志，含区域时存放在 `region` 子目录。`logs_zh` / `logs_en` 固定存在，其余语言按有译文才出现：`{"logs_zh": {...}, "logs_en": {...}, "logs_zh_tw": {...}, "logs_ja": {...}, ...}`（语言集合见 `scripts/miroms/constants.py` 的 `CHANGELOG_LOCALES`；与站点 21 种语言一致） |
| `api/v3/dev/index.json` | 开发版（周更）周次索引：`latest` / `oldest` / `regions` 与 `weeks` 列表（每项含周数、区域 cn/global、大版本、版本号、中英标题、发布日期、机型数与已收录语言） |
| `api/v3/dev/<region>/<week>.json` | 开发版单周详情：公告标题/正文/升级说明、机型清单（`devices`）、ROM 清单（`roms`）与多语言更新日志 `logs`（结构与 `v3/logs/**` 一致，前端按当前语言取用） |
| `api/v3/roms/<OS>.json` | 按系统版本分组的 ROM 列表（如 `OS1.json` = HyperOS 1），每项含设备、版本、Android、区域、分支名、日期、包文件名，按需按版本号拼接成设备 ROM 表 |
| `api/v3/releases/<year>.json` | 按发布日期分组的 ROM 列表，结构为 `{"year": "2026", "dates": {"2026-09-18": [{"device": "brussels", "version": "OS3.0.308.0.WDRMIXM", "region": "global"}, ...]}}`，供前端按日期查询时只拉取某一年的数据 |
| `api/v3/releases/index.json` | 发布日期索引元信息：`generatedAt` 生成时间、`minDate` / `maxDate` 可查询日期范围、`totalRoms` 总数与 `years`（每年的 ROM 数与有发布记录的天数） |
| `api/v3/index.json` | 设备索引：每台设备的名称、品牌、系列（`series`）、代码、Android 版本、支持的系统版本、支持区域（`regions`，可见分支的区域去重）、支持运营商（`carriers`，可见分支的运营商去重，排除空值）、区域与运营商的对应关系（`regionCarriers`，形如 `{"cn": ["chinatelecom", ...]}`）、分支数（`branchCount`）与 ROM 数（`romCount`） |
| `api/v3/series.json` | 机型系列：系列列表（品牌、中英文名、`device_ids` 设备归属）与设备排序（`order`） |
| `api/v3/stats.json` | 近期统计：`generatedAt` 生成时间、`recentDays` 统计天数、`recentRoms` 近期新增 ROM 数、`recent` 近期 ROM 明细列表 |
| `api/v3/sitelog.json` | hub 自身的站点日志：`{"generatedAt", "sites": {"hub.web": {site, latest, count, logs}, "hub.admin": {...}}}`，每条形如 `{ver, date, log: [{zh, en}]}`（按版本倒序，最新在前）。条目由 `scripts/import_hub_sitelog.py` 按 git 记录导入 `sitelog` 表后导出；官网前端读 `sites['hub.web']`，管理后台直连数据库读 `site='hub.admin'` |
| `api/v3/tools.json` | 刷机工具下载（供官网「工具下载」页）：`{"generatedAt", "source", "tools": [{tool, name: {zh, en}, packages: [{version, date, filename, url, attentions: [{zh, en}], logs: [{zh, en}]}]}]}`；人工维护的 `api/v1/tools.json` 是唯一手写源，导出时把 `zh-cn` / `en-us` 转成 `zh` / `en`、`FileName` 转成 `filename` |

### 多语言更新日志

更新日志来自 `update.miui.com`：请求表单里的 `l` 参数决定返回哪种语言，小米没有提供译文的语种会回落英文。因此新增语种时先用 `--probe` 确认接口到底认哪个 locale——例如阿拉伯语只有 `ar_EG` 有译文，`ar` / `ar_SA` / `ar_AE` 等都会回落英文。步骤：

1. 先在 `scripts/miroms/constants.py` 的 `CHANGELOG_LOCALES` 里登记语种（列名 / 接口 locale / 站点 locale）
2. 给 `logs` 表加同名列：结构见 `db_structure/logs.sql`，列集合随 `CHANGELOG_LOCALES` 自动生成（`roms` 表**不再需要改动**）
3. `python3 scripts/fetch_changelog.py --probe 5` 先看接口对哪些语种返回了独立译文（不写库）
4. `python3 scripts/fetch_changelog.py --langs ja,ko,ru` 按语种补数据；不加参数则依次处理全部语种

处理时按 ROM id 批量进行：先把候选 ROM 的 `logs` 解回各语言，挑出缺该语种的 id；遍历 id 并集时同一个 ROM 只查库一次、只构建一次请求表单，命中多个语种时仅替换 `l` 参数各请求一次，最后把该 ROM 的全部语言一次性写回（`LogStore.write_logs`：分组写入 `logs` 表 → `UPDATE roms.logs`）。

写入失败会计入 `write_failed` 并打印首个错误；`--dry-run` 可以只看将写入什么而不落库。回落到英文的语种会被自动跳过（该语种不写入），确需写入时加 `--force`。

#### 自增 id 空档

InnoDB 的 `AUTO_INCREMENT` 在**插入失败 / 事务回滚**时不会回收（MySQL 的既有行为），
抓取脚本偶发失败就会烧掉一个 id；而且本项目与 HyperOS.fans、NuxtMR **三个项目的抓取脚本
共用同一个 `miroms` 库**（各自的 `scripts/config.py` 都指向它），空档因此会缓慢累积
（例如 `roms` 一度是 54622 行却已经自增到 54634）。导入脚本里也要避免
`INSERT ... ON DUPLICATE KEY UPDATE` 做「有则更新」——命中重复键时同样会推进计数器
（`dev` 表曾因此每次导入烧掉几百个 id，现已改为先查再 `UPDATE`）。

清理方式（可重复执行）：

```bash
python3 scripts/resequence_ids.py                 # 只看 roms 的空档
python3 scripts/resequence_ids.py --table dev     # 只看 dev
python3 scripts/resequence_ids.py --table logs    # 只看 logs（重排会同步重写引用）
python3 scripts/resequence_ids.py --apply         # 重排 roms 并归位计数器
python3 scripts/resequence_ids.py --table logs --apply
python3 scripts/resequence_ids.py --verify        # 只校验是否连续
```

`logs.id` 被 `roms.logs` / `dev.logs` 引用，不能像 `roms` / `dev` 那样直接重排：
`--table logs` 会走 `LogMaintenance.compact_ids`，在**同一个事务**里「整体 +1000000 →
赋 ROW_NUMBER()」，随后按旧→新映射重写全部引用并归位计数器；整段在跨进程写锁内执行，
写库前自动把 logs 全表与引用结构备份成 JSON（`--no-backup` 可跳过）。

#### 日志维护（去重 / content / 掩码 / id / 孤儿行）

通用逻辑收敛在 `scripts/miroms/logs_maintenance.py` 的 `LogMaintenance`，
文本判定收敛在 `logs_text.py` 的 `LogText`；脚本只做参数解析与打印：

```bash
python3 scripts/maintain_logs.py                        # 体检（只读）：重复、悬空引用、坏 JSON、
                                                        # 孤儿行、content 不一致、哈希过期、掩码、id 空档
python3 scripts/maintain_logs.py --report /tmp/audit.json
python3 scripts/maintain_logs.py content --apply        # 以 logs_zh 为准重建 content / content_hash
python3 scripts/maintain_logs.py masks --apply          # 补齐掩码（只补本 ROM 已声明过的语言）
python3 scripts/maintain_logs.py masks --clean-invalid --apply  # 删除「模块行已无该语言」的无效掩码位
python3 scripts/maintain_logs.py prefix --apply          # 去掉 content/语言列开头的空白和标点（* 除外）
python3 scripts/maintain_logs.py ids --apply            # 压缩 logs id + 重写引用（自动备份）
python3 scripts/maintain_logs.py unused --apply         # 删除未被引用的日志行
python3 scripts/maintain_logs.py auto-increment --apply # logs.AUTO_INCREMENT 归位到 MAX(id)+1
python3 scripts/maintain_logs.py merge --groups "11040:1" --apply  # 按显式分组合并（引用自动重写）
python3 scripts/maintain_logs.py snapshot --out /tmp/logs_before.json.gz
python3 scripts/maintain_logs.py compare --before /tmp/logs_before.json.gz
```

所有动作默认 dry-run，只有 `--apply` 才写库。掩码补齐「只增不减」，不会让任何 ROM 的导出结果回退；
补位只在本 ROM / 开发版自己声明过的语言范围内进行——`logs` 行跨 ROM 复用，别的 ROM 可能把共享行
补齐了全部译文，越过这个范围补位会把不属于本 ROM 的语言写进掩码；
`ids` / `unused` 属于破坏性操作，都会先刷新导出缓存。

`merge` 用于「自动去重无法判定」的场景：两行中文相同，但一方的某门外语其实只是英文回落
（值等于本行 `logs_en`，如 `id=1` 的 `logs_de='Other'`），另一方有真实译文（如 `id=11040`
的 `logs_de='Sonstiges'`）。严格规则会把回落值当冲突而漏合并；`merge_groups` 会优先保留真实译文、
再用回落值补空缺，并按代表行重写引用。

`snapshot` 会把每个 `roms` / `dev` 行解出的多语言日志拍成快照（默认 gzip，约 80–90 MB）；
在去重 / 补掩码 / 压缩 id 之后再跑 `compare`，逐条对比「新增 / 消失的文本、语言与模块名」，
检测到内容丢失（文本减少、语言减少或整行消失）时退出码为 1——比抽样检查可靠，和以前一次性脚本的
「导出回归」口径一致。

纯逻辑（文本判定、去重计划、引用重排、content / 掩码 / 孤儿行体检）有单元测试，不连数据库：

```bash
python3 scripts/test_logs_maintenance.py
```

#### 日志 AI 校对（DeepSeek，可选）

同一 ROM 的不同语言结构会被拆成「中文簇 + 附加语言簇」。早期按模块名 / 条目数猜测补译的脚本
可能把中文填错，例如 `id=11036`（德文 `Interkonnektivität`）和 `id=11038`
（`Datenschutz und Sicherheit`）都被填成了「其他」，而真正的「其他」是 `id=11040`
（`Sonstiges`）。这类问题会同时制造「同一 ROM 多个同名中文模块」和「导出中文重复」。
`proofread_logs.py` 把它做成可重复的流程，默认全程 dry-run：

```bash
# 1) 只校对某几个 logs.id（不改日志内容；verdict=ok 时写 proofed 标记）
python3 scripts/proofread_logs.py check --ids 11036
python3 scripts/proofread_logs.py check --ids 11036,11038
python3 scripts/proofread_logs.py check --ids 3788 --no-ai          # 只做规则检查
python3 scripts/proofread_logs.py check --ids 2998 --json /tmp/check.json

# 2) 全库扫描 → AI 复核 → 计划 → 写库
python3 scripts/proofread_logs.py scan --report /tmp/proofread_scan.json
python3 scripts/proofread_logs.py review --scan /tmp/proofread_scan.json --cache /tmp/proofread_cache.json --decisions /tmp/proofread_decisions.json
python3 scripts/proofread_logs.py apply --decisions /tmp/proofread_decisions.json --allow-clear
python3 scripts/proofread_logs.py apply --decisions /tmp/proofread_decisions.json --allow-clear --apply
```

`check` 是单条校对（不改日志内容，只更新 proofed）：打印该行的 `content` / `zh` / 各语言文本、英文回落列、疑似译文错列、
同 ROM 的中文模块名，然后给出 AI 的 `verdict`（ok / wrong_zh / mixed_translations / extra_module）、
建议中文、置信度和理由。加 `--decisions /tmp/fix.json` 可以把 module 的 wrong_zh 结论写成 decisions，
再交给 `apply` 执行（默认 dry-run）。

批量校对有三档，默认都**只估算、不调用 API**，加 `--run` 才真正执行：

```bash
# 档 1：只跑冲突 family（推荐先做，约 60 万 tokens）
python3 scripts/proofread_logs.py review --limit 0 --decisions /tmp/f_decisions.json

# 档 2：全部多语言行，10 条/批（约 250–300 万 tokens，约 400 次调用）
python3 scripts/proofread_logs.py batch-review --batch-size 10
python3 scripts/proofread_logs.py batch-review --batch-size 10 --run

# 档 3：逐条全量（不推荐：1,100–2,000 万 tokens、1 万次调用；
#        含 7,156 条只有一种语言的行，没有跨语言校对价值）
python3 scripts/proofread_logs.py batch-review --batch-size 1 --all
python3 scripts/proofread_logs.py batch-review --batch-size 1 --all --run --allow-expensive
```

`batch-review` 的特点：

- 默认只选 **≥2 种语言** 的行（3,918 行），`--all` 才包含单语言行；
- 先打印行数、批次数、Prompt / Completion / 合计 token 和预计耗时，**不加 `--run` 不会花钱**；
- 超过 800 万 tokens 或 5,000 次调用时，必须 `--run --allow-expensive` 双重确认；
- `--limit-rows N` 可先抽样；`--cache` 断点续跑；`--types module,log` 可只审一类；
- 结果写入 `--decisions`，再交给 `apply`；**log 条目的改法不会自动写库**，只报告；
- AI 结论**每批立即落库**（`lang_issues` / `proofed`），11k 行跑到一半中断也不会丢已完成的标注。

单条校对：

```bash
python3 scripts/proofread_logs.py check --ids 11036
```

- `scan`：纯规则，不调用 AI。找出「同一 ROM 内多个 module 中文名相同、真实外文却不同」的
  family（排除等于本行 `logs_en` 的英文回落）；同时用「译文 → 中文」共现统计报告疑似译文错列
  （只报告，不自动改）。
`proofed` 标记：`review` / `batch-review` / `check` 拿到 `verdict=ok` **且没有任何语言不符**时，
才把该行 `proofed` 置 1；之后的扫描 / 复核默认跳过这些行。任何内容改动（补语言、合并、`content` 重建、
`apply` 改名/清空）都会把 `proofed`、`complete` 和 `lang_issues` 一起重置，需要重新校对。

`complete` 标记：只有**全部语言列都有内容且 `proofed=1`** 时才为 1；`proofed` 被重置、语言列被
清空/修改，或仍有缺失语言时为 0。可用 `python3 scripts/maintain_logs.py complete --apply`
按现有数据重算。

语言核查：每次 AI 校对会逐语言判断「该列文本是否真的属于这门语言」（列对照见
`LogProofreader.LANG_NAMES`），不符的列写入 `logs.lang_issues`；另外「某列值与 `logs_en` 完全相同」
会以 0.75 置信度自动标注为英文回落（AI 的明确判断优先）。有 `lang_issues` 的行不置 `proofed=1`。
`check` 会逐条打印 `logs_de 实际='英文' (0.98) ...` 这样的标注。要强制复查已标记的行，用
`check --force`；`--no-mark` 则完全不写 `proofed` / `lang_issues`。

mixed_translations 两步修复：

```bash
# 只扫描指定行（推荐先小样本）
python3 scripts/fix_mixed_translations.py --ids 760,1483,1611

# 扫描当前全部多语言行（耗时/耗 token）
python3 scripts/fix_mixed_translations.py --scan --limit 500

# 复用已校验的 decisions
python3 scripts/fix_mixed_translations.py --decisions /tmp/proofread_batch_decisions.json

# 执行合并 / 拆分（默认只读；写前备份）
python3 scripts/fix_mixed_translations.py --ids 760 --apply-merges
python3 scripts/fix_mixed_translations.py --ids 1611 --apply-splits
```

第一步：中文翻英文 → 找相似行 → AI 判断是否同一内容 → 合并并重写引用。
第二步：AI 按语义把语言聚簇 → 每簇新建一行并 AI 补齐缺失语言 → 按引用掩码与簇原始语言的交集路由；
交集并列/为 0 的位置保留原行并标记待人工，不自动拆。

旧转义还原：

```bash
python3 scripts/restore_log_escapes.py            # 预览
python3 scripts/restore_log_escapes.py --apply    # 写库（写前备份）
```

旧代码把 `'` / `"` 写成 `^`、`%` 写成 `$$`；现在列存储不再需要。还原规则：
`won^t → won't`、`l^écran → l'écran`、`^Service & feedback^ → "Service & feedback"`、
`^^文本^^ → "文本"`、`5$$ → 5%`。默认保留 proofed / complete / lang_issues（机械还原不改语义）。

proofed 行缺失语言回填：

```bash
python3 scripts/fill_missing_logs.py                    # 盘点 proofed 行缺口 + token 估算
python3 scripts/fill_missing_logs.py --ids 23           # 只看指定行
python3 scripts/fill_missing_logs.py --expected owners  # 只补引用里实际出现过的语言
python3 scripts/fill_missing_logs.py --run              # 调 AI 预览译文，不写库
python3 scripts/fill_missing_logs.py --apply            # 调 AI 并写库（写前备份）
python3 scripts/fill_missing_logs.py --apply --keep-proofed

# 分批：--offset / --limit（每批独立进程，避免单次调用过多）
python3 scripts/fill_missing_logs.py --offset 0 --limit 20 --apply --keep-proofed --max-calls 20
```

- 默认期望语言是全部语言列；`--expected owners` 只补该行在 `roms` / `dev` 掩码里实际出现过的语言；
- 以 `logs_zh` / `content` / `logs_en` 为源翻译；置信度低于 `--min-confidence`（默认 0.8）不写；
- 译文与英文源完全相同视为无效，避免又写回英文回落；
- 默认 `--apply` **每行拿到译文就立即写库**，中断不会丢已完成行；`--atomic` 则全部跑完再统一写；
- 回填后默认 `proofed=0`（新增译文需要重新校对）；`--keep-proofed` 且无剩余 `lang_issues` 时保留 1；
- 回填列会从 `lang_issues` 移除，全部移除后置 NULL；缓存可断点续跑。

按标注修正语言列：

```bash
python3 scripts/fix_lang_issues.py                       # 预览全部有标注的行
python3 scripts/fix_lang_issues.py --ids 1,165           # 只处理指定 logs.id
python3 scripts/fix_lang_issues.py --apply               # 用 AI 的 correct 替换（无 correct 保留原值）
python3 scripts/fix_lang_issues.py --mode translate --apply # 没有 correct 的条目调用 AI 翻译回填（每行即时写库）
python3 scripts/fix_lang_issues.py --mode hybrid --apply # 无 correct 时才清空
python3 scripts/fix_lang_issues.py --mode clear --apply  # 显式清空错误语言列
python3 scripts/fix_lang_issues.py --mode move --apply   # 能映射到空语言列时移动
python3 scripts/fix_lang_issues.py --clean-masks --apply # 同步去掉引用掩码里的对应位
```

- 默认 `--mode correct`：`lang_issues` 里 `correct` 非空且 `confidence >= --min-confidence`（默认 0.8）
  才替换；没有 `correct` 或置信度不足时**保留原值并继续标注，不删除**；
- `--mode hybrid` 才会在无正确译文时清空，`--mode clear` 是显式删除；
- `logs_zh` / `logs_en` 不动（除非 `--allow-core`，替换/清空核心列时会自动重建
  `content` / `content_hash`）；
- 修正后从 `lang_issues` 移除已处理项；全部处理完时显式 `UPDATE ... lang_issues = NULL`，`proofed` 重置为 0；
- `--clean-masks` 会把 module 行被清空的语言从 `roms` / `dev` 引用掩码里去掉；
- 写库前可选备份（默认系统临时目录），建议先 `maintain_logs.py snapshot` 再 `compare`。

- `review`：每个 family 调一次 DeepSeek，先判定 `verdict`：
  `ok`（当前中文正确）/ `wrong_zh`（中文确实填错，译文一致指向另一个中文名）/
  `mixed_translations`（中文可能正确，但不同语言译文指向不同模块 = 译文错列 / 互换）/
  `extra_module`（中文结构里没有的额外模块）。`wrong_zh` 只能从该 ROM 已有的中文模块名里选，
  `extra_module` 返回 null；prompt 按内容哈希缓存，中断后可续跑。
- `apply`：`rename` 改正完整行（带 logs_en 且语言多）的中文；`clear` 清掉附加语言簇窄行
  （无 logs_en、语言 ≤6）的中文并同步去掉引用掩码的中文位；`mixed_translations` 只报告，
  不自动改（译文换列需要另一套修复）；低置信度 / 意见冲突 / 未加 `--allow-clear` 的也只报告。
  语言很多但没有 logs_en 的行（可能是合法语言簇）即使 AI 判为中文错误也只报告——实测清空这类行
  会丢掉部分 ROM 独有的中文条目译文。
  写库前自动备份，写后建议再跑 `maintain_logs.py audit` 与 `snapshot` / `compare`。

API key 二选一（环境变量优先）：

```bash
export DEEPSEEK_API_KEY=sk-...
# 或填写 data/scripts/config.py 的 deepseek_api_key（另有 deepseek_base_url / deepseek_model）
```

成本控制：`review --limit N` 限制 family 数，`--max-calls N` 限制请求数，`--cache` 复用结果；
`--all` 才会复核非 priority 候选（默认只处理「窄行 / 无英文」这类高风险 family）。

校对逻辑的纯函数（扫描、prompt 构造、AI 返回校验、动作计划）有单元测试，不连库、不调用真实 API：

```bash
python3 scripts/test_logs_proofread.py
```

#### 本地校对 / 补译（LM Studio + Hunyuan-MT-7B）

Hunyuan-MT-7B 是纯翻译模型，适合逐条补写缺失语言，并用「重译对比」校对现有译文。
在 LM Studio 里加载模型并 Start Server（默认 `http://127.0.0.1:1234`）后即可使用，
默认走 LM Studio 原生接口 `POST /api/v1/chat`（`system_prompt` 放翻译指令、`input` 放源文本），
不需要 API key：

```bash
python3 scripts/local_translate.py check --probe              # 服务 / 模型 / 试翻
python3 scripts/local_translate.py fill --limit 50            # 盘点缺口（不调模型）
python3 scripts/local_translate.py fill --ids 146 --run       # 预览补译
python3 scripts/local_translate.py fill --ids 146 --apply     # 补译写库（写前备份）
python3 scripts/local_translate.py review --langs logs_en --limit 200 --run
python3 scripts/local_translate.py review --langs logs_en --ids 146 --fix
python3 scripts/local_translate.py all --limit 200 --apply --fix

本地语言校验（逐条判断译文是否真的使用该列语言）与本地模型替换：

```bash
python3 scripts/local_lang_check.py check --ids 5135,4444 --show 20   # 预览
python3 scripts/local_lang_check.py check --all --apply               # 全量标注 lang_issues
python3 scripts/local_lang_check.py check --all --report /tmp/langcheck.json
python3 scripts/local_lang_check.py fix --ids 5135 --langs logs_ja --apply
python3 scripts/local_lang_check.py fix --all --apply                 # 全量替换（耗时）
```

- `check`：规则层（文字体系 / 与 logs_en 相同 / 简繁转换 / 俄乌字母）+ 本地 fastText
  `lid.176` 语种识别；只在高置信度时标注，短词与维吾尔/藏文交给文字体系规则，避免误报；
- `fix`：对 `lang_issues` 列用 LM Studio 的 Hunyuan-MT 从中文重译并替换，复用
  `LogFiller.apply`（备份、清 `lang_issues`、`proofed=0`）；
- 依赖：`pip install fasttext-wheel`，模型 `~/.cache/langid/lid.176.ftz`
  （可用环境变量 `LANGID_MODEL` 指定）。
```

- 接口切换：默认原生 `/api/v1/chat`；如改用 OpenAI 兼容端点，加 `--api openai`（或设置
  `LMSTUDIO_API=openai` / `config.py` 的 `lmstudio_api`），地址仍填服务根地址即可
  （`http://127.0.0.1:1234/v1` 也会自动识别）；
- 提示词用官方模板：中文方向 `把下面的文本翻译成<目标语言>，不要额外解释。`，其余方向英文模板；
- 译文校验：占位符（`%s` / `{0}`）、提示词回显、非中文列混入汉字、目标语言特征文字（俄 / 乌 / 阿 / 维 / 藏 / 泰 / 印地 / 日 / 韩）；
- 校对：把源文本重译后与现有译文做相似度比较，长文本低于 `--ratio`（默认 0.75）、短文本低于 `--short-ratio`（默认 0.45）判为可疑，`--fix` 才用重译结果替换；
- 写库复用 `LogFiller.apply()`：自动备份、清理 `lang_issues`、`proofed` 重置为 0；`--expected owners` 只补引用里出现过的语言，`--workers` 并发，`--cache` 复用结果。

#### 日志去重（必须校验）

`logs` 表按内容跨 ROM 复用分组，**写入侧只做「语言不冲突即可复用」的匹配**：
写入前把整张 `logs` 表载入内存行池（`LogStore.load_index`），按「类型相同 + 各语言不冲突」
认领已有分组，冲突时另起一行。这样同一日志即使主内容不同（`#25 content=相册` 与
`#27 content=Gallery`）也能合并，不会像早期实现那样只按 `content_hash` 找候选而漏掉。

配套的兜底校验（以下位置发现重复即报错退出）：

| 位置 | 说明 |
| --- | --- |
| `python3 scripts/dedup_logs.py` | 体检并列出可合并分组；`--apply` 合并、`--prune-unused` 清理孤儿行 |
| `python3 scripts/maintain_logs.py` | 一次性体检：重复分组、悬空引用、坏 JSON、孤儿行、content 不一致 / 哈希过期、掩码可补位 / 无效位、id 空档 |
| `import_dev_week.py` / `migrate_logs_multilang.py` | 导入 / 迁移结束后自动调用 `LogStore.duplicate_report()`，有重复即退出码 1 |
| 管理后台 `/logs` 页「去重体检」 | `GET /api/logs/audit`：重复分组、重复行数、未被 `roms`/`dev` 引用的孤儿行数 |

判定标准：类型相同、各语言文本互不冲突、且至少共享一门语言文本 → 本应是同一行。
合并只做「并集 + 重写引用」，语言掩码保持不变，因此各 ROM 的导出结果与合并前逐字一致。
算法实现在 `LogMaintenance.duplicate_plan`（中文分桶 + 桶内逐对兼容合并），
`dedup_logs.py` 只是它的命令行入口，其他脚本可直接复用同一套计划 / 执行方法。
合并会把各语言文本取并集，因此合并后可以用 `maintain_logs.py masks --apply` 再把新出现的公共语言位补进掩码。

#### 日志存储结构（同一日志多语言共用一行）

原先 `roms` 表有 21 个 `logs_*` 列（一门语言一列），同一句日志的不同语言版本各自去重、互不关联。现在改为：

* **`logs` 表** —— 同一日志的各语言版本共用一行：`id` / `type`（`module` 模块名、`log` 条目）/ `content`（主内容，中文优先；无中文时取英文）/ `content_hash`（`md5(content)`，查专用索引）/ `proofed`（AI 校对通过标记：`1` 表示该行内容已被 AI 判为一致，后续 `scan` / `review` / `batch-review` / `check` 默认跳过）/ `complete`（全部语言列都有内容且 `proofed=1`）/ `lang_issues`（AI 语言标注 JSON，如 `{"logs_de":{"detected":"英文","confidence":0.98}}`，有标注的行不会置 `proofed=1`）/ `logs_zh`、`logs_zh_tw`、`logs_en` … `logs_bo`（各语言原文，一门语言一列）。
* **`roms.logs`** —— 单一的语言中性 ID 引用结构：`[[模块ID, [条目ID, ...], 语言掩码], ...]`。语言掩码为 21 位整数（第 i 位对应 `CHANGELOG_LOCALES` 第 i 个语言列），表示该位置属于本 ROM 的哪几门语言。`roms` 不再有 `logs_*` 列，新增语种也不必再改 `roms`。

两个关键设计（都在 `scripts/miroms/logs_store.py`）：

1. **结构指纹聚类**：中文日志的模块 / 条目序号并不总和其他语言对应（例如某 ROM 的中文是「电话 / 联系人 / 短信 / 便签」四个模块，而日文、德文只返回一个「其他」模块）。因此只有**结构指纹完全一致**（模块数、每个模块条目数都相同）的语言才按序号合并成同一组；指纹不同的语言各自成组，作为附加模块并入总日志——即「其他语言提到、但中英文没提到的日志也一并加进总日志」。
2. **语言掩码 + 冲突拆行**：`logs` 表按内容跨 ROM 复用，掩码保证导出时只输出该位置在本 ROM 真正拥有的语言，避免 A 语言的模块被 B 语言输出带出去；同一主内容若在不同 ROM 出现互相冲突的译文，则另起一行保存（`(type, content_hash)` 只是普通索引），保证每个 ROM 的日志都能原样还原。

> 迁移：`python3 scripts/migrate_logs_multilang.py`（旧 `logs` 表改名为 `logs_legacy` 保留，核对无误后可 `DROP TABLE logs_legacy`）。迁移按「结构指纹聚类」重新分组，并以独立的备份库做过交叉校验：47 万余条「ROM × 语言」结构的还原结果与迁移前逐字一致。
>
> 规范化：主内容会去掉首尾空白（旧数据里有 91 条仅靠首尾空格区分的重复原文），因此少数导出的日志条目不再带多余的前后空格。

#### 开发版（周更）数据

`dev` 表按「周数 + 区域」存放开发版公告：同一周数会有两条记录——大陆版 `region=cn`（zone 1）与国际版 `region=global`（zone 2），各自有独立的公告、日志和机型列表。字段见 `db_structure/dev.sql`。

**机型 / ROM 清单不单独存 JSON**（早期版本存过 `devices` / `roms` 两列，约 1.2 MB 重复数据，已删除，见 `db_structure/migrations/20261016_dev_drop_json.sql`）：

```sql
-- 第 N 周（某区域）有哪些机型与 ROM
SELECT r.device, r.version, r.android, r.release_date, r.recovery, r.fastboot
  FROM roms r
  JOIN dev d ON d.week = r.dev_week AND d.zone = r.zone
 WHERE d.week = 500 AND d.region = 'cn';
```

机型名走 `devices` 表，版本号 / Android / 发布日期 / 卡刷线刷包全部读 `roms` 本身，导出（`export_dev`）与后台绑定页都按上面的关系现算，因此 `dev` 表只保留公告与日志这类真正独有的数据（387 行约 64 KB）。

导入参考仓库的数据：

```bash
python3 scripts/import_dev_week.py --source hyperos    # HyperOS.fans/public/data/dev/<week>.json
python3 scripts/import_dev_week.py --source nuxtmr     # NuxtMR/public/MRData/data/weekly/week-<week>-cn.json
python3 scripts/import_dev_week.py --source miuiroms   # MIUIROMS/weekly/logs/week-<week>-CN.html
python3 scripts/import_dev_week.py --all --dry-run     # 全部来源，只统计不写库
python3 scripts/import_dev_week.py --backfill-roms     # 仅按发布日期回填 roms.dev_week
```

* 日志按上面的方法存档：以中文结构为依据重新分组写入 `logs` 表，`dev.logs` 只存语言中性的 ID 引用结构。
* **以中文为依据修正英文**：元数据里的英文是人工翻译、与官方有出入，导入时会先在 `logs` 表里按中文反查官方英文，命中就用官方译文，未命中才保留元数据里的翻译。
* `expand_mask=True` 会把语言掩码扩展到「模块与全部条目的公共语言」，因此复用到库里已有多语言分组时，能顺带带出中英文之外的其他译文。
* **机型绑定（写 `roms.dev_week`）**分三级：
  1. 主规则——按**该周版本号**绑定：`roms.version = 该周 versions AND zone = 该周 zone AND branch = 'X'`
     （版本号唯一标识这一周的开发版，任何带该版本的机型都属于本周）；
  2. 补充规则——公告机型表里逐机型带版本号的行（部分周次各机型版本号并不相同，如 NuxtMR）；
  3. 退化规则——既没有版本号也没有机型表时，按 `branch='X'` + 区域 + 发布日期匹配。
  仍绑不上的周次（老周报只有机型列表没有版本号、延期公告把日期写进正文）留空，
  在管理后台「开发版绑定」页手动关联，绑定关系本身就是 `roms.dev_week`，不额外建表。
* 版本号识别会排除日期：「全机型预计11.2日24点前发布」这类延期公告不再把 `11.2` 当成版本号。
* MIUIROMS 的 HTML 页面里「支持机型」是独立的 `<table>`：解析时会先把表格摘掉再提取日志正文
  （否则表格行会被当成日志条目，历史上确实混入过「机型 / 卡刷包 / miui_XXX.zip」这类脏数据），
  表格本身用于机型绑定与发布日期兜底（机型号里的 `(cepheus)` 直接取代号，否则按 `devices` 表的中英文名反查）。
  `▍发布时间` 一节会按内容拆分：日期进 `release_date`、版本号进 `versions`、`MIUI V5` / `MIUI 12.5` 进 `bigver`，
  原文一并存进 `description`；解析器还会统计「疑似表格内容」并在发现时打印告警。

#### 站点日志（sitelog 表）

两个参考站点的站点日志原先各自手写在仓库里，结构不同：

* NuxtMR：`{"log": [{sudate, ver, zh-cn, en-us, log: [{zh-cn, en-us}]}]}`
* HyperOS.fans：`{"icons": [...], "logs": [{siteVer, icon, date, log: [{zh, en}]}]}`

hub 自身（官网前端 `hub.web`、管理后台 `hub.admin`）的更新日志则直接按 git 记录推导，
仓库没有 git tag，因此**按提交日期分版**：每个项目在该路径下的提交按作者日期分组，
日期升序依次编号 `V0.1.0`、`V0.2.0`…，最新一版即当前版本（git 历史只在末尾追加，既有版本号稳定）。
提交标题会去掉对项目冗余的 `[web]` / `[admin]` / `[root]` / `[data]` 前缀与 `feat(web):` 这类作用域。

现在统一存 `sitelog` 表（见 `db_structure/sitelog.sql`），用 `site` 列区分站点、`kind` 列区分行类型：

```bash
python3 scripts/import_sitelog.py --all                  # 参考站点（nuxtmr 76 条 + hyperos.fans 45 条）
python3 scripts/import_sitelog.py --source nuxtmr        # 只导入 NuxtMR
python3 scripts/import_sitelog.py --dry-run              # 只统计不写库

python3 scripts/import_hub_sitelog.py --dry-run          # hub 自身：预览两个项目的版本划分
python3 scripts/import_hub_sitelog.py                    # hub 自身：hub.web 17 版 + hub.admin 13 版
python3 scripts/import_hub_sitelog.py --drop-types chore,build,docs   # 只保留 feat/fix 等面向用户的提交
```

* `kind='entry'` 为日志条目：`ver` / `icon` / `log_date` / `devices_zh` / `devices_en` / `logs`（`[{"zh","en"},...]`），`sort_order` 越小越靠前（0 = 最新）。
* `kind='meta'` 为站点级元信息：目前只有 HyperOS.fans 的 `icons` 调色板（前端未使用，保留源站数据）。
* 站内版本号允许重复（NuxtMR 有两条 `V0.5.5-SNAPSHOT`、两条 `V0.3.8-SNAPSHOT`），唯一键带上 `log_date`。
* git 推导的条目只在标题本身不含中日韩字符时填 `en`，其余留空——前端在译文缺失时回退中文。
* 落库统一走 `miroms/sitelog_store.py`（按唯一键原地 UPDATE，不烧自增 id）。
* 导出：`export_sitelog('nuxtmr')` → `api/v1/sitelog.json`，`export_sitelog('hyperos.fans')` → `api/v2/sitelog.json`（导入 + 导出与源文件逐字段一致，已核对）；`export_hub_sitelog()` → `api/v3/sitelog.json`（hub.web / hub.admin 两条线）。

---

## 数据库结构 / Database Schema

数据库使用 MySQL（InnoDB，utf8mb4），表结构与字段含义见 `db_structure/`：

- **`devices.sql`** — 设备表：设备代号（`device`）、内部标识（`devtag`）、设备代码（`code`）、ROM 标签（`tag`）、区域（`region`）、运营商（`carrier`）、品牌（`brands` / `full_brands`）、中英文名（`full_names` / `names` / `xiaomi` / `redmi` / `poco`）、图片（`image`）、发布日期（`launch_date`）
- **`roms.sql`** — ROM 表：系统类型（`type`：MIUI / HyperOS）、大版本（`bigver`）、区域、标签、分支（`branch`：F=正式版 / X=开发版）、完整版本号（`version`）、Android 版本、发布日期（`beta_date` / `release_date` / `public_date`）、Recovery / Fastboot / 运营商定制包文件名（`recovery` / `fastboot` / `ctelecom` / `cmobile` / `cunicom` / `others`）、更新日志（`logs`，语言中性的 ID 引用结构 `[[模块ID,[条目ID,...],语言掩码],...]`）、开发版周数（`dev_week`，反查 `dev` 表）、安全补丁日期（`aspatch`）
- **`logs.sql`** — 更新日志表：`type`（`module` 模块名 / `log` 条目）、`content`（主内容，中文优先）、`content_hash`（`md5(content)`）、以及 21 个语言列（`logs_zh` / `logs_zh_tw` / `logs_en` / `logs_ja` / `logs_ko` / `logs_ru` / `logs_uk` / `logs_pl` / `logs_de` / `logs_fr` / `logs_it` / `logs_es` / `logs_pt` / `logs_tr` / `logs_id` / `logs_vi` / `logs_th` / `logs_ar` / `logs_in` / `logs_ug` / `logs_bo`）——同一日志的各语言版本共用一行
- **`dev.sql`** — 开发版（周更）表：`week` + `region`（cn / global）唯一，含大版本、版本号、中英标题、公告正文（`description`）、升级说明（`attention`）、停版机型（`suspended`）、日志 ID 结构（`logs`）与数据来源（`source`）；机型 / ROM 清单由 `roms.dev_week` + `zone` 现算，不另存 JSON
- **`branches.sql`** — 分支表：分支类型、中英文名称、标签（`tag`）、代码后缀（`code`）、版本代码（`vercode`）、运营商、区域、分区（`zone`）、可见性（`visibility`）、是否政企版（`ep`）
- **`series.sql`** — 机型系列表：品牌（`brand`：xiaomi / redmi / poco）、中英文名称（`name_zh` / `name_en`）、设备归属（`device_ids`，JSON 数组）、排序（`sort_order`）
- **`sitelog.sql`** — 站点日志表：`site` 区分站点（`nuxtmr` → `api/v1/sitelog.json`、`hyperos.fans` → `api/v2/sitelog.json`、`hub.web` / `hub.admin` → `api/v3/sitelog.json`），`kind` 区分行类型（`entry` 日志条目 / `meta` 站点级元信息如 `icons` 调色板），含版本号（`ver`）、图标（`icon`）、日期（`log_date`）、新增机型摘要（`devices_zh` / `devices_en`）与日志正文（`logs`，`[{"zh","en"},...]`）

---

## 数据脚本 / Scripts

`scripts/` 为纯 Python 3 实现（无第三方依赖），模块化结构如下：

| 文件 | 说明 |
| --- | --- |
| `exporter.py` | 入口脚本：遍历 `common.fullDevices` 依次执行 `exportV1` / `exportV2` / `exportV3`，再执行 `export_dev()` 导出 `api/v3/dev/**`、`export_v1_extras()` / `export_v2_extras()` 导出两个参考站点的附属接口（见「V1 / V2 附属文件」）与 `export_hub_extras()` 导出 `api/v3/sitelog.json` / `api/v3/tools.json`，完成后调用 `app/web/scripts/generate-index.mjs`（Node.js）重新生成 `api/v3/index.json`、`api/v3/stats.json`、`api/v3/roms/*.json` 与 `api/v3/releases/*.json` |
| `migrate_logs_multilang.py` | 把 `roms` 的 21 个 `logs_*` 列迁移为「`logs` 多语言分组 + `roms.logs` 单列」；旧表保留为 `logs_legacy`，`--dry-run` 只统计，`--verify N` 抽查中英文一致性；结束时自动跑去重体检 |
| `resequence_ids.py` | 把 `roms` / `dev` / `logs` 的 id 重排成连续自增并归位自增计数器（消除 `AUTO_INCREMENT` 空档）；roms / dev 先采样 20 秒确认无人写入，并把「旧 id → 新 id」映射写到 `.backup/*_id_map_*.csv`；`logs` 走 `LogMaintenance.compact_ids`，在事务内改 id + 重写 `roms.logs` / `dev.logs` 引用，写库前备份 logs 全表与引用为 JSON |
| `dedup_logs.py` | `logs` 去重体检与合并：把「同一日志被拆成多行」的分组并成一行，同步重写 `roms.logs` / `dev.logs` 引用（掩码不变，导出结果不受影响）；`--apply` 实际合并（自动备份）、`--prune-unused` 顺带清理孤儿行 |
| `maintain_logs.py` | `logs` 统一维护入口：`audit`（默认，只读体检）/ `complete`（重算 complete 标记）/ `prefix`（去掉 content/语言列开头的空白和标点，`*` 除外）/ `content`（以 `logs_zh` 为准重建 content）/ `masks`（补齐语言掩码，只增不减）/ `ids`（压缩 id + 重写引用）/ `unused`（清理孤儿行）/ `auto-increment` / `merge`（按显式分组合并，回落值让位于真实译文）/ `snapshot`（导出快照）/ `compare`（对比快照，检测内容丢失）；默认 dry-run，写库加 `--apply` |
| `fix_mixed_translations.py` | `mixed_translations` 两步修复：扫描当前行或复用 decisions；第一步翻译英文、找相似行、AI 对比后合并；第二步 AI 语言聚簇、拆成新行并按掩码语言交集路由引用，歧义位置跳过；默认只读，`--apply-merges` / `--apply-splits` 才写库 |
| `restore_log_escapes.py` | 还原旧 JSON 存储时代的转义：`^`→`'`/`"`、`$$`→`%`；默认保留 `proofed` / `complete` / `lang_issues`，`--reset-flags` 则重置；`--apply` 写前备份 |
| `fill_missing_logs.py` | 对 `proofed=1` 的行排查缺失语言并用 AI 翻译回填：默认只盘点/估算；`--run` 预览；`--apply` 写库（写前备份）；`--expected all\|owners`、`--langs`、`--min-confidence`；默认回填后 `proofed=0`，`--keep-proofed` 可保留 |
| `local_translate.py` | 用 LM Studio 本地 Hunyuan-MT-7B 逐条补写缺失语言 / 校对现有译文：`check` 检查服务与模型；`fill` 补译（`--apply` 写库）；`review` 重译对比（`--ratio` / `--short-ratio`，`--fix` 才替换）；`all` 同时处理；提示词用官方模板，校验占位符 / 提示词回显 / 目标语言文字；写库复用 `LogFiller.apply`（备份、清 `lang_issues`、`proofed=0`） |
| `local_lang_check.py` | 本地语言校验：规则 + fastText `lid.176` 逐单元格判断译文语言，命中写 `lang_issues`；`fix` 用 Hunyuan-MT 从中文重译替换；`check --all --apply` 全量扫描 6.5 万单元格约 1–2 秒，`fix` 逐条调用模型较慢 |
| `fix_lang_issues.py` | 按 `logs.lang_issues` 修正语言列：默认 `correct`（用 AI 的 `correct` 正确译文替换，无 correct/低置信度保留原值）；`--mode translate` 对没有 correct 的标注调用 AI 翻译回填并逐条清除 lang_issues；`--mode hybrid` 无译文才清空，`--mode clear` 显式删除，`--mode move` 移到正确空列，`--clean-masks` 同步去掉引用掩码位；核心列需 `--allow-core`；默认 dry-run，写前备份 |
| `proofread_logs.py` | 日志多语言校对：`check --ids` 校对指定 logs.id（不改内容，ok 时写 proofed）；`scan` 用规则找「同一 ROM 多个同名中文模块但外文含义不同」的候选；`review` 调 DeepSeek 判断每行真正对应的中文模块名（只能从该 ROM 的中文模块名里选，或 null = 额外模块）；`apply` 按置信度改名 / 清空额外模块中文并清理掩码中文位；`batch-review` 批量/逐条审全部多语言行（默认只估算，`--run` 才调用，ok 行自动 proofed）；除 proofed 标记外不改日志内容 |
| `rebuild_roms_logs.py` | 以迁移前的备份库为权威来源重建 `roms.logs`（修复人工改动 `logs` 表造成的悬空引用），并复核「无悬空引用」 |
| `import_dev_week.py` | 导入开发版（周更）数据到 `dev` 表并回填 `roms.dev_week`；支持 `--source hyperos\|nuxtmr\|miuiroms`、`--all`、`--weeks 619-652`、`--region global`、`--dry-run`、`--backfill-roms` |
| `import_sitelog.py` | 把 NuxtMR / HyperOS.fans 两个站点的站点日志（`sitelog.json`）导入 `sitelog` 表，`--source nuxtmr\|hyperos`、`--all`、`--root`、`--dry-run`；按唯一键原地更新，幂等且不烧自增 id |
| `import_hub_sitelog.py` | 按 git 记录推导 hub 自身（`hub.web` = `app/web`、`hub.admin` = `app/admin`）的更新日志并写入 `sitelog` 表：按提交日期分版编号 `V0.1.0`…，`--site`、`--drop-types chore,build,docs`、`--dry-run` |
| `migrate_v1v2_assets.py` | 把参考仓库里的静态接口文件、机型目录与「仅存于参考仓库的遗留机型」播种到 `api/v1` / `api/v2`；默认只补缺失，`--force` 可强制覆盖静态文件（设备文件始终不覆盖），`--with-images` 额外把机型图片复制到 `api/v2/assets/images`（默认不搬，规范位置是 `images/`） |
| `sync_devices.py` | 从 `devices` / `roms` 表同步设备列表到 `miroms/data.py`（`fullDevices`、`currentStable`、`flags`） |
| `fix_missing_tag_mappings.py` | 修复 `devices` 表中缺失的 device+tag 映射（V3 导出器按 tag 匹配分支，缺失会导致 ROM 丢失），输出 SQL 到 stdout 或 `--apply` 直接执行 |
| `common.py` | 向后兼容入口，重新导出 `miroms` 包全部公共 API，并保留 `fullDevices`、`currentStable`、`flags` 等模块级常量 |
| `config.py` | 数据库连接配置（host / port / user / password / database）+ Cloudflare Pages 部署配置（`api` 基础地址 + `ids` 站点钩子列表，默认三个站点：HUB / HyperOS.fans / MIUIer）+ DeepSeek 校对配置（`deepseek_api_key` / `deepseek_model` / `deepseek_base_url` / `deepseek_reasoning_effort`；key 也可用环境变量 `DEEPSEEK_API_KEY` 提供）+ LM Studio 本地翻译配置（`lmstudio_base_url` / `lmstudio_model` / `lmstudio_timeout`） |
| `push.py` | 一键全流程：运行 `exporter.py` 导出 → 在 `data` 子仓库提交并推送（commit message 为当前日期时间）→ 调用 `deploy.py` 依次部署 `config.ids` 中的所有站点（站点之间默认停留 10 秒），任一站点失败即以非 0 退出码结束 |
| `deploy.py` | 仅触发部署：按 `config.ids` 顺序 POST `{config.api}/{id}`（Cloudflare Pages deploy hook），逐个打印站点名、部署 ID / short_id / URL，每个 hook 触发后默认停留 10 秒再触发下一个站点（`--interval` 可调，0 表示不等待）；可传站点名或 hook id 前缀只部署指定站点（如 `python3 scripts/deploy.py HUB`），`--list` 只列出目标；全部成功退出码为 0，否则为 1 |
| `miroms/` | 核心包：`constants.py`（常量、SDK 版本、Android 代号、分支表、语种表）、`data.py`（设备列表）、`database.py`（数据库访问 + 事务）、`network.py` / `crypto.py` / `firmware.py`（小米服务器抓取与解密）、`recorder.py`（数据录入）、`changelog.py`（更新日志）、`logs_store.py`（日志多语言分组读写）、`logs_text.py`（文本判定 + 繁简转换）、`logs_maintenance.py`（日志去重 / 引用重写 / content 一致性 / 语言掩码 / id 压缩 / 体检）、`logs_proofread.py`（日志多语言校对 / AI 复核）、`deepseek.py`（DeepSeek API 客户端）、`local_mt.py`（LM Studio 本地翻译客户端 + Hunyuan-MT 提示词 / 译文校验）、`sitelog_store.py`（站点日志落库）、`validator.py`（校验）、`exporters.py`（V1/V2/V3 + 开发版导出器）、`legacy_exporters.py`（api/v1 = NuxtMR、api/v2 = HyperOS.fans、api/v3 = hub 自身的站点附属接口导出）、`utils.py`（工具函数） |

### 抓取 / 部署脚本

| 文件 | 说明 |
| --- | --- |
| `get_new_branch.py` | Fastboot + OTA 探测，发现新分支 / 新版本 |
| `ota_former.py` | OTA 版本检测 |
| `ota_full.py` | 全量 OTA 偏移探测 |
| `xfu_full.py` | 本地 HTML 核查 |
| `get_current_fastboot.py` | 抓取当前 Fastboot 包信息 |
| `mgc_fastboot.py` | 小米社区 API 抓取 |
| `fetch_changelog.py` | 抓取多语言更新日志（changelog）与卡刷包；`--probe` 探测接口对哪些语种真的返回译文，`--langs` 指定语种，`--force` 连英文回落也写入 |
| `aspatch.py` | 提取安全补丁（Android Security Patch）日期 |
| `test.py` | 调试 / 验证脚本（非流水线步骤） |

以上抓取脚本也可通过 VS Code Tasks（主仓库 `.vscode/tasks.json`，`Ctrl+Shift+B`）一键运行。

### 生成流程 / Pipeline

```
小米更新服务器 (update.miui.com)
        │  network / crypto / firmware 抓取并解密
        ▼
MySQL 数据库 (miroms: devices / roms / logs / dev / branches / series)
        │  python3 scripts/sync_devices.py        → 更新 miroms/data.py 设备列表
        │  python3 scripts/fix_missing_tag_mappings.py --apply（必要时）
        │  python3 scripts/migrate_logs_multilang.py        → 日志多语言分组（一次性）
        │  python3 scripts/dedup_logs.py --apply --prune-unused  → 日志去重体检 / 合并 / 清理
        │  python3 scripts/maintain_logs.py（定期）      → 日志体检 / content / 掩码 / id 空档
        │  python3 scripts/import_dev_week.py --all         → 开发版周更数据（dev 表）
        │  python3 scripts/exporter.py            → 导出 api/v1|v2|v3 + dev + index.json / series.json
        ▼
JSON 数据（api/）
        │  python3 scripts/push.py（导出 → git commit & push → 按 config.ids 触发部署）
        ▼
Cloudflare Pages（deploy hook）自动部署
        → api.miuier.com（CNAME，见根目录 CNAME 文件）
        → HUB / HyperOS.fans / MIUIer 三个站点
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
# 直接读取设备数据（GitHub Raw）
curl -fsSL https://raw.githubusercontent.com/HegeKen/miroms/master/api/v3/devices/agate.json

# 或通过 Cloudflare Pages 站点读取（CNAME: api.miuier.com，站点根是仓库根，数据在 /api 下）
curl -fsSL https://api.miuier.com/api/v3/devices/agate.json
```

前端站点（`appBaseUrl` 为 `https://api.miuier.com/api`）、管理后台与移动端（Android / iOS / 小程序）均为本仓库数据的消费者；各消费者代码见主仓库 [HegeKen/hub.miuier.com](https://github.com/HegeKen/hub.miuier.com) 的 `app/` 目录。

---

## 相关文档 / Related Docs

| 文档 | 简体中文 | English |
| --- | --- | --- |
| 项目总览 | [../README.md](../README.md) | [../README_EN.md](../README_EN.md) |
| 前端站点 | [../app/web/README.md](../app/web/README.md) | [../app/web/README_EN.md](../app/web/README_EN.md) |
| 管理后台 | [../app/admin/README.md](../app/admin/README.md) | [../app/admin/README_EN.md](../app/admin/README_EN.md) |
| 本仓库 | [README.md](README.md) | [README_EN.md](README_EN.md) |

---

## Credits

本仓库的数据管线依赖以下运行时、平台与数据源，谨向各作者与社区致谢。

| 名称 | 用途 | 许可 |
| --- | --- | --- |
| [Python 3](https://www.python.org/) | `scripts/` 全部抓取 / 导出 / 部署脚本（仅用标准库） | PSF-2.0 |
| [Node.js](https://nodejs.org/) | `../app/web/scripts/generate-index.mjs` 生成 v3 索引、按年分片与 `releases/*.json` | MIT |
| [MySQL](https://www.mysql.com/) | 数据存储（InnoDB / utf8mb4；`devices` / `roms` / `logs` / `dev` / `branches` / `series`） | GPL-2.0 / 商业许可 |
| [Cloudflare Pages](https://pages.cloudflare.com/) | `api.miuier.com` 托管与 deploy hook 自动部署 | Cloudflare 服务条款 |
| [GitHub](https://github.com/) | 仓库托管、子模块与 Raw 分发 | GitHub 服务条款 |
| 小米更新服务器（`update.miui.com`） | ROM 版本号、下载地址与更新日志（经 `network` / `crypto` / `firmware` 抓取解密） | 数据与商标归小米科技所有 |
| 小米社区（Mi Community） | Fastboot 包信息（`mgc_fastboot.py`） | 数据与商标归小米科技所有 |

> MIUI、HyperOS、Xiaomi、Redmi、POCO 等为小米科技或其关联公司的商标；本仓库与小米科技无隶属关系。

---

## License

[Apache License 2.0](LICENSE)
