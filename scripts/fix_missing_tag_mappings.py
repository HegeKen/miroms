#!/usr/bin/env python3
"""
修复 devices 表中缺失的 tag 映射，使 V3 导出器能完整导出所有 ROM 数据。

问题根因：V3 导出器按 tag 匹配分支，只有 devices 表中存在的 device+tag 组合才会被导出。
当前数据库中有 ~27,000 条 ROM 因 devices 表缺少对应 tag 映射而丢失。

使用方法：
  python3 fix_missing_tag_mappings.py          # 生成 SQL 到 stdout
  python3 fix_missing_tag_mappings.py --apply  # 直接执行 SQL（需确认）
"""

import sys
from miroms.database import DatabaseManager

# 分支 tag 到代码后缀的映射（来自 constants.py branches）
TAG_CODE_SUFFIX = {
    'CnOO': '',
    'CnOB': '',
    'Beta': '',
    'Dev': '',
    'CNAL': '_alpha',
    'CNST': '',
    'CNTT': '',
    'CNUT': '',
    'CNLT': '',
    'GOST': '',
    'CnOD': '_demo',
    'EPSTD': '_ep_stdee',
    'EPSCE': '_ep_stdce',
    'EPYKE': '_ep_yunke',
    'EPXYE': '_ep_xy',
    'EPYYE': '_ep_yy',
    'EPSDL': '_ep_sdlybjcg',
    'EPTBK': '_ep_tbkj',
    'EPTLE': '_tl',
    'EPTLY': '_ep_tly',
    'EPXDJ': '_ep_xdja',
    'EPYXE': '_ep_yx',
    'EPKYW': '_ep_kywl',
    'EPCQR': '_ep_cqrcb',
    'EPECE': '_ep_ec',
    'EPSXH': '_ep_sxht',
    'EPYFA': '_ep_yfan',
    'EPTKG': '_ep_tkgwdl',
    'EPCJC': '_ep_cjcc',
    'ADPC': '_pre_dpp',
    'CNHK': '_hk_global',
    'CNTP': '_tw_global',
    'GDev': '_global',
    'GBOO': '_global',
    'GBDC': '_dc_global',
    'GBHG': '_h3g_global',
    'ADPG': '_pre_dpp_global',
    'EEAO': '_eea_global',
    'EUOR': '_eea_or_global',
    'EUVF': '_eea_vf_global',
    'EUHG': '_eea_hg_global',
    'EUTF': '_eea_tf_global',
    'EUSF': '_eea_sf_global',
    'EUTI': '_eea_ti_global',
    'EUBY': '_eea_by_global',
    'RUSO': '_ru_global',
    'INSO': '_in_global',
    'INRF': '_in_rf_global',
    'IDSO': '_id_global',
    'MYGS': '',
    'SGGS': '_sg_global',
    'SGGD': '_sg_global',
    'THAS': '_th_as_global',
    'TRSO': '_tr_global',
    'JPKD': '_jp_kd_global',
    'JAPS': '_jp_global',
    'JPSB': '_jp_sb_global',
    'SKSO': '_kr_global',
    'SKLG': '_kr_gu_global',
    'SKKT': '_kr_kt_global',
    'SKSK': '_kr_sk_global',
    'LMCR': '_lm_cr_global',
    'MXTC': '_mx_tc_global',
    'CLEN': '_cl_en_global',
    'MXAT': '_mx_at_global',
    'ZAMT': '_za_mt_global',
    'ZAVC': '_za_vc_global',
    'LMMS': '_lm_ms_global',
    'GTTG': '_gt_tg_global',
    'IDDM': '_id_global',
    # 新增标签（不在 constants.py 中，需要手动添加后缀）
    'EPLTE': '_ep_litee',
    'EPCJCC': '_ep_cjcc',
    'EPCMC': '_ep_cmcc',
    'EEAD': '_eea_global',
    'CNXM': '',
    'MIXM': '_global',
}


def main():
    apply_mode = '--apply' in sys.argv

    # 1. 查询所有缺失的 device+tag 组合
    missing_sql = """
        SELECT DISTINCT r.device, r.tag
        FROM roms r
        LEFT JOIN devices d ON r.device = d.device AND r.tag = d.tag
        WHERE r.type IN ('MIUI','HyperOS') AND d.id IS NULL
        ORDER BY r.tag, r.device
    """
    missing = DatabaseManager.execute(missing_sql, fetch_one=False)

    if not missing:
        print("-- 没有缺失的 tag 映射，无需修复")
        return

    print(f"-- 共发现 {len(missing)} 个缺失的 device+tag 组合")
    print("--" + "=" * 60)

    # 2. 对每个缺失组合，查询现有设备条目的信息作为模板
    insert_sqls = []
    for device, tag in missing:
        # 查询该设备已有的条目作为参考
        existing_sql = """
            SELECT devtag, devcode, carrier, branchcode,
                   full_brands, brands, full_names, names,
                   xiaomi, redmi, poco, image, launch_date
            FROM devices WHERE device = %s LIMIT 1
        """
        existing = DatabaseManager.execute(existing_sql, params=(device,), fetch_one=True)

        # 确定 code
        suffix = TAG_CODE_SUFFIX.get(tag, '')
        code = f"{device}{suffix}" if suffix else device

        # 确定 region
        branch_regions = {
            'CnOO': 'cn', 'CnOB': 'cn', 'Beta': 'cn', 'Dev': 'cn',
            'CNAL': 'cn', 'CNST': 'cn', 'CNTT': 'cn', 'CNUT': 'cn',
            'CNLT': 'cn', 'GOST': 'cn', 'CnOD': 'cn',
            'EPSTD': 'cn', 'EPSCE': 'cn', 'EPYKE': 'cn', 'EPXYE': 'cn',
            'EPYYE': 'cn', 'EPSDL': 'cn', 'EPTBK': 'cn', 'EPTLE': 'cn',
            'EPTLY': 'cn', 'EPXDJ': 'cn', 'EPYXE': 'cn', 'EPKYW': 'cn',
            'EPCQR': 'cn', 'EPECE': 'cn', 'EPSXH': 'cn', 'EPYFA': 'cn',
            'EPTKG': 'cn', 'EPCJC': 'cn', 'ADPC': 'cn', 'EPLTE': 'cn',
            'EPCJCC': 'cn', 'EPCMC': 'cn',
            'CNHK': 'hk', 'CNTP': 'tw',
            'GDev': 'global', 'GBOO': 'global', 'GBDC': 'global',
            'GBHG': 'global', 'ADPG': 'global',
            'EEAO': 'eea', 'EUOR': 'eea', 'EUVF': 'eea', 'EUHG': 'eea',
            'EUTF': 'eea', 'EUSF': 'eea', 'EUTI': 'eea', 'EUBY': 'eea',
            'EEAD': 'eea',
            'RUSO': 'ru', 'INSO': 'in', 'INRF': 'in',
            'IDSO': 'id', 'IDDM': 'id', 'MYGS': 'my',
            'SGGS': 'sg', 'SGGD': 'sg', 'THAS': 'th',
            'TRSO': 'tr', 'JPKD': 'jp', 'JAPS': 'jp', 'JPSB': 'jp',
            'SKSO': 'kr', 'SKLG': 'kr', 'SKKT': 'kr', 'SKSK': 'kr',
            'LMCR': 'lm', 'MXTC': 'mx', 'CLEN': 'cl', 'MXAT': 'mx',
            'ZAMT': 'za', 'ZAVC': 'za', 'LMMS': 'lm', 'GTTG': 'gt',
            'CNXM': 'cn', 'MIXM': 'global',
        }
        region = branch_regions.get(tag, 'cn')

        if existing:
            devtag, devcode, carrier, branchcode, full_brands, brands, full_names, names, xiaomi, redmi, poco, image, launch_date = existing
        else:
            devtag = devcode = carrier = branchcode = ''
            full_brands = '["Xiaomi"]'
            brands = '"Xiaomi"'
            full_names = names = xiaomi = redmi = poco = '{}'
            image = None
            launch_date = None

        # 构建 INSERT 语句
        def sql_val(v):
            if v is None:
                return 'NULL'
            s = str(v).replace("'", "\\'")
            return f"'{s}'"

        fields = [
            'device', 'devtag', 'code', 'tag', 'region', 'devcode',
            'carrier', 'branchcode', 'full_brands', 'brands',
            'full_names', 'names', 'xiaomi', 'redmi', 'poco',
            'image', 'launch_date'
        ]
        values = [
            sql_val(device), sql_val(devtag), sql_val(code), sql_val(tag),
            sql_val(region), sql_val(devcode), sql_val(carrier),
            sql_val(branchcode), sql_val(full_brands), sql_val(brands),
            sql_val(full_names), sql_val(names), sql_val(xiaomi),
            sql_val(redmi), sql_val(poco), sql_val(image), sql_val(launch_date)
        ]

        sql = f"INSERT INTO devices ({', '.join(fields)}) VALUES ({', '.join(values)});"
        insert_sqls.append(sql)

    # 输出 SQL
    print("\nBEGIN;")
    for sql in insert_sqls:
        print(sql)
    print("COMMIT;")

    print(f"\n-- 共生成 {len(insert_sqls)} 条 INSERT 语句")

    # 预估影响
    affected_roms_sql = """
        SELECT COUNT(*) AS cnt
        FROM roms r
        LEFT JOIN devices d ON r.device = d.device AND r.tag = d.tag
        WHERE r.type IN ('MIUI','HyperOS') AND d.id IS NULL
    """
    result = DatabaseManager.execute(affected_roms_sql, fetch_one=True)
    print(f"-- 预计可恢复 {result[0]} 条 ROM 数据")

    if apply_mode:
        print("\n-- 正在执行 SQL...")
        for sql in insert_sqls:
            try:
                DatabaseManager.execute(sql)
            except Exception as e:
                print(f"-- 警告: {e}", file=sys.stderr)
        print("-- 修复完成!")
    else:
        print("\n-- 要直接执行，请运行: python3 fix_missing_tag_mappings.py --apply")


if __name__ == '__main__':
    main()
