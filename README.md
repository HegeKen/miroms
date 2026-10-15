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
│   ├── v1/devices/<codename>.json    # V1：MIUI 设备数据（旧格式）
│   ├── v2/devices/<codename>.json    # V2：HyperOS 设备数据
│   ├── v3/devices/<codename>.json    # V3：全量设备数据（MIUI + HyperOS）
│   ├── v3/logs/<device>/[region/]<version>.json   # V3：多语言更新日志
│   ├── v3/dev/index.json             # V3：开发版（周更）周次索引
│   ├── v3/dev/<region>/<week>.json   # V3：开发版单周公告 + 机型清单 + 多语言日志
│   ├── v3/roms/<OS>.json             # V3：按系统版本（OS1/OS2/OS3…）分组的 ROM 列表
│   ├── v3/releases/<year>.json       # V3：按发布日期分组的 ROM 列表（按年份分片）
│   ├── v3/releases/index.json        # V3：发布日期索引的元信息（日期范围 / 年份统计）
│   ├── v3/index.json                 # V3：设备索引（设备列表 + 统计）
│   ├── v3/series.json                # V3：机型系列数据（series 表导出）
│   └── v3/stats.json                 # V3：近期更新统计
├── db_structure/                     # MySQL 表结构
│   ├── devices.sql                   #   设备表
│   ├── roms.sql                      #   ROM 表
│   ├── logs.sql                      #   更新日志表（同一日志多语言共用一行）
│   ├── dev.sql                       #   开发版（周更）表
│   ├── branches.sql                  #   分支表
│   ├── series.sql                    #   机型系列表
│   └── migrations/                   #   schema 迁移 SQL
├── scripts/                          # 数据同步 / 抓取 / 导出 / 部署脚本（Python）
│   ├── exporter.py                   #   主导出脚本
│   ├── migrate_logs_multilang.py     #   日志多语言分组迁移（logs 重建 + roms.logs 回写）
│   ├── dedup_logs.py                 #   logs 去重体检 / 合并重复分组 / 清理孤儿行
│   ├── rebuild_roms_logs.py          #   按备份库重建 roms.logs（修复悬空引用）
│   ├── import_dev_week.py            #   导入开发版周更数据（dev 表 + roms.dev_week）
│   ├── sync_devices.py               #   同步设备列表
│   ├── fix_missing_tag_mappings.py   #   修复缺失 tag 映射
│   ├── common.py                     #   向后兼容入口（重新导出 miroms 包）
│   ├── config.py                     #   数据库连接配置 + 部署 hook
│   ├── push.py                       #   一键导出 → 提交推送 → 部署
│   ├── deploy.py                     #   触发 Cloudflare Pages 部署
│   ├── *.py                          #   各类抓取脚本（见下文「抓取 / 部署脚本」）
│   └── miroms/                       #   核心包（常量/工具/抓取/导出等）
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

### 多语言更新日志

更新日志来自 `update.miui.com`：请求表单里的 `l` 参数决定返回哪种语言，小米没有提供译文的语种会回落英文。因此新增语种时先用 `--probe` 确认接口到底认哪个 locale——例如阿拉伯语只有 `ar_EG` 有译文，`ar` / `ar_SA` / `ar_AE` 等都会回落英文。步骤：

1. 先在 `scripts/miroms/constants.py` 的 `CHANGELOG_LOCALES` 里登记语种（列名 / 接口 locale / 站点 locale）
2. 给 `logs` 表加同名列：结构见 `db_structure/logs.sql`，列集合随 `CHANGELOG_LOCALES` 自动生成（`roms` 表**不再需要改动**）
3. `python3 scripts/fetch_changelog.py --probe 5` 先看接口对哪些语种返回了独立译文（不写库）
4. `python3 scripts/fetch_changelog.py --langs ja,ko,ru` 按语种补数据；不加参数则依次处理全部语种

处理时按 ROM id 批量进行：先把候选 ROM 的 `logs` 解回各语言，挑出缺该语种的 id；遍历 id 并集时同一个 ROM 只查库一次、只构建一次请求表单，命中多个语种时仅替换 `l` 参数各请求一次，最后把该 ROM 的全部语言一次性写回（`LogStore.write_logs`：分组写入 `logs` 表 → `UPDATE roms.logs`）。

写入失败会计入 `write_failed` 并打印首个错误；`--dry-run` 可以只看将写入什么而不落库。回落到英文的语种会被自动跳过（该语种不写入），确需写入时加 `--force`。

#### 日志去重（必须校验）

`logs` 表按内容跨 ROM 复用分组，**写入侧只做「语言不冲突即可复用」的匹配**：
写入前把整张 `logs` 表载入内存行池（`LogStore.load_index`），按「类型相同 + 各语言不冲突」
认领已有分组，冲突时另起一行。这样同一日志即使主内容不同（`#25 content=相册` 与
`#27 content=Gallery`）也能合并，不会像早期实现那样只按 `content_hash` 找候选而漏掉。

配套的兜底校验（三处都会跑，发现重复即报错退出）：

| 位置 | 说明 |
| --- | --- |
| `python3 scripts/dedup_logs.py` | 体检并列出可合并分组；`--apply` 合并、`--prune-unused` 清理孤儿行 |
| `import_dev_week.py` / `migrate_logs_multilang.py` | 导入 / 迁移结束后自动调用 `LogStore.duplicate_report()`，有重复即退出码 1 |
| 管理后台 `/logs` 页「去重体检」 | `GET /api/logs/audit`：重复分组、重复行数、未被 `roms`/`dev` 引用的孤儿行数 |

判定标准：类型相同、各语言文本互不冲突、且至少共享一门语言文本 → 本应是同一行。
合并只做「并集 + 重写引用」，语言掩码保持不变，因此各 ROM 的导出结果与合并前逐字一致。

#### 日志存储结构（同一日志多语言共用一行）

原先 `roms` 表有 21 个 `logs_*` 列（一门语言一列），同一句日志的不同语言版本各自去重、互不关联。现在改为：

* **`logs` 表** —— 同一日志的各语言版本共用一行：`id` / `type`（`module` 模块名、`log` 条目）/ `content`（主内容，中文优先；无中文时取英文）/ `content_hash`（`md5(content)`，查专用索引）/ `logs_zh`、`logs_zh_tw`、`logs_en` … `logs_bo`（各语言原文，一门语言一列）。
* **`roms.logs`** —— 单一的语言中性 ID 引用结构：`[[模块ID, [条目ID, ...], 语言掩码], ...]`。语言掩码为 21 位整数（第 i 位对应 `CHANGELOG_LOCALES` 第 i 个语言列），表示该位置属于本 ROM 的哪几门语言。`roms` 不再有 `logs_*` 列，新增语种也不必再改 `roms`。

两个关键设计（都在 `scripts/miroms/logs_store.py`）：

1. **结构指纹聚类**：中文日志的模块 / 条目序号并不总和其他语言对应（例如某 ROM 的中文是「电话 / 联系人 / 短信 / 便签」四个模块，而日文、德文只返回一个「其他」模块）。因此只有**结构指纹完全一致**（模块数、每个模块条目数都相同）的语言才按序号合并成同一组；指纹不同的语言各自成组，作为附加模块并入总日志——即「其他语言提到、但中英文没提到的日志也一并加进总日志」。
2. **语言掩码 + 冲突拆行**：`logs` 表按内容跨 ROM 复用，掩码保证导出时只输出该位置在本 ROM 真正拥有的语言，避免 A 语言的模块被 B 语言输出带出去；同一主内容若在不同 ROM 出现互相冲突的译文，则另起一行保存（`(type, content_hash)` 只是普通索引），保证每个 ROM 的日志都能原样还原。

> 迁移：`python3 scripts/migrate_logs_multilang.py`（旧 `logs` 表改名为 `logs_legacy` 保留，核对无误后可 `DROP TABLE logs_legacy`）。迁移按「结构指纹聚类」重新分组，并以独立的备份库做过交叉校验：47 万余条「ROM × 语言」结构的还原结果与迁移前逐字一致。
>
> 规范化：主内容会去掉首尾空白（旧数据里有 91 条仅靠首尾空格区分的重复原文），因此少数导出的日志条目不再带多余的前后空格。

#### 开发版（周更）数据

`dev` 表按「周数 + 区域」存放开发版公告：同一周数会有两条记录——大陆版 `region=cn`（zone 1）与国际版 `region=global`（zone 2），各自有独立的公告、日志和机型列表。字段见 `db_structure/dev.sql`（标题、版本号、公告正文、升级说明、机型清单、ROM 清单、停版机型、日志 ID 结构等）。

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
* 机型匹配：优先按元数据的 `device + version` 精确回填 `roms.dev_week`；没有机型清单的来源（HTML）则按 `branch='X'` + 区域 + 发布日期回填。
* MIUIROMS 的 HTML 页面里「支持机型」是独立的 `<table>`：解析时会先把表格摘掉再提取日志正文
  （否则表格行会被当成日志条目，历史上确实混入过「机型 / 卡刷包 / miui_XXX.zip」这类脏数据），
  表格本身会解析成 `devices` / `roms`（机型号里的 `(cepheus)` 直接取代号，否则按 `devices` 表的中英文名反查）。
  `▍发布时间` 一节会按内容拆分：日期进 `release_date`、版本号进 `versions`、`MIUI V5` / `MIUI 12.5` 进 `bigver`，
  原文一并存进 `description`；解析器还会统计「疑似表格内容」并在发现时打印告警。

---

## 数据库结构 / Database Schema

数据库使用 MySQL（InnoDB，utf8mb4），表结构与字段含义见 `db_structure/`：

- **`devices.sql`** — 设备表：设备代号（`device`）、内部标识（`devtag`）、设备代码（`code`）、ROM 标签（`tag`）、区域（`region`）、运营商（`carrier`）、品牌（`brands` / `full_brands`）、中英文名（`full_names` / `names` / `xiaomi` / `redmi` / `poco`）、图片（`image`）、发布日期（`launch_date`）
- **`roms.sql`** — ROM 表：系统类型（`type`：MIUI / HyperOS）、大版本（`bigver`）、区域、标签、分支（`branch`：F=正式版 / X=开发版）、完整版本号（`version`）、Android 版本、发布日期（`beta_date` / `release_date` / `public_date`）、Recovery / Fastboot / 运营商定制包文件名（`recovery` / `fastboot` / `ctelecom` / `cmobile` / `cunicom` / `others`）、更新日志（`logs`，语言中性的 ID 引用结构 `[[模块ID,[条目ID,...],语言掩码],...]`）、开发版周数（`dev_week`，反查 `dev` 表）、安全补丁日期（`aspatch`）
- **`logs.sql`** — 更新日志表：`type`（`module` 模块名 / `log` 条目）、`content`（主内容，中文优先）、`content_hash`（`md5(content)`）、以及 21 个语言列（`logs_zh` / `logs_zh_tw` / `logs_en` / `logs_ja` / `logs_ko` / `logs_ru` / `logs_uk` / `logs_pl` / `logs_de` / `logs_fr` / `logs_it` / `logs_es` / `logs_pt` / `logs_tr` / `logs_id` / `logs_vi` / `logs_th` / `logs_ar` / `logs_in` / `logs_ug` / `logs_bo`）——同一日志的各语言版本共用一行
- **`dev.sql`** — 开发版（周更）表：`week` + `region`（cn / global）唯一，含大版本、版本号、中英标题、公告正文（`description`）、升级说明（`attention`）、停版机型（`suspended`）、机型清单（`devices`）、ROM 清单（`roms`）、日志 ID 结构（`logs`）与数据来源（`source`）
- **`branches.sql`** — 分支表：分支类型、中英文名称、标签（`tag`）、代码后缀（`code`）、版本代码（`vercode`）、运营商、区域、分区（`zone`）、可见性（`visibility`）、是否政企版（`ep`）
- **`series.sql`** — 机型系列表：品牌（`brand`：xiaomi / redmi / poco）、中英文名称（`name_zh` / `name_en`）、设备归属（`device_ids`，JSON 数组）、排序（`sort_order`）

---

## 数据脚本 / Scripts

`scripts/` 为纯 Python 3 实现（无第三方依赖），模块化结构如下：

| 文件 | 说明 |
| --- | --- |
| `exporter.py` | 入口脚本：遍历 `common.fullDevices` 依次执行 `exportV1` / `exportV2` / `exportV3`，再执行 `export_dev()` 导出 `api/v3/dev/**`，完成后调用 `app/web/scripts/generate-index.mjs`（Node.js）重新生成 `api/v3/index.json`、`api/v3/stats.json`、`api/v3/roms/*.json` 与 `api/v3/releases/*.json` |
| `migrate_logs_multilang.py` | 把 `roms` 的 21 个 `logs_*` 列迁移为「`logs` 多语言分组 + `roms.logs` 单列」；旧表保留为 `logs_legacy`，`--dry-run` 只统计，`--verify N` 抽查中英文一致性；结束时自动跑去重体检 |
| `dedup_logs.py` | `logs` 去重体检与合并：把「同一日志被拆成多行」的分组并成一行，同步重写 `roms.logs` / `dev.logs` 引用（掩码不变，导出结果不受影响）；`--apply` 实际合并，`--prune-unused` 顺带清理孤儿行 |
| `rebuild_roms_logs.py` | 以迁移前的备份库为权威来源重建 `roms.logs`（修复人工改动 `logs` 表造成的悬空引用），并复核「无悬空引用」 |
| `import_dev_week.py` | 导入开发版（周更）数据到 `dev` 表并回填 `roms.dev_week`；支持 `--source hyperos\|nuxtmr\|miuiroms`、`--all`、`--weeks 619-652`、`--region global`、`--dry-run`、`--backfill-roms` |
| `sync_devices.py` | 从 `devices` / `roms` 表同步设备列表到 `miroms/data.py`（`fullDevices`、`currentStable`、`flags`） |
| `fix_missing_tag_mappings.py` | 修复 `devices` 表中缺失的 device+tag 映射（V3 导出器按 tag 匹配分支，缺失会导致 ROM 丢失），输出 SQL 到 stdout 或 `--apply` 直接执行 |
| `common.py` | 向后兼容入口，重新导出 `miroms` 包全部公共 API，并保留 `fullDevices`、`currentStable`、`flags` 等模块级常量 |
| `config.py` | 数据库连接配置（host / port / user / password / database）+ Cloudflare Pages 部署 hook（`deploy_url`） |
| `push.py` | 一键全流程：运行 `exporter.py` 导出 → 在 `data` 子仓库提交并推送（commit message 为当前日期时间）→ 调用 `deploy.py` 触发站点部署 |
| `deploy.py` | 仅触发部署：POST `config.deploy_url`（Cloudflare Pages deploy hook）并打印部署 ID |
| `miroms/` | 核心包：`constants.py`（常量、SDK 版本、Android 代号、分支表、语种表）、`data.py`（设备列表）、`database.py`（数据库访问）、`network.py` / `crypto.py` / `firmware.py`（小米服务器抓取与解密）、`recorder.py`（数据录入）、`changelog.py`（更新日志）、`logs_store.py`（日志多语言分组读写）、`validator.py`（校验）、`exporters.py`（V1/V2/V3 + 开发版导出器）、`utils.py`（工具函数） |

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
        │  python3 scripts/import_dev_week.py --all         → 开发版周更数据（dev 表）
        │  python3 scripts/exporter.py            → 导出 api/v1|v2|v3 + dev + index.json / series.json
        ▼
JSON 数据（api/）
        │  python3 scripts/push.py（导出 → git commit & push → 触发部署）
        ▼
Cloudflare Pages（deploy hook）自动部署 → api.miuier.com（CNAME，见根目录 CNAME 文件）
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

# 或通过 Cloudflare Pages 站点读取（CNAME: api.miuier.com）
curl -fsSL https://api.miuier.com/v3/devices/agate.json
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
