import common
import json

# 单机型 changelog 探针，参考 NuxtMR/public/MRData/scripts/getChangelog.py 的写法：
# 指定机型 → 填字段 → 加密请求 → 打印更新日志（不依赖数据库，改下面几个变量即可）
# 注意：r 必须是小写（大写 R 是历史误加字段）。实测接口并不按 r 过滤，
# 换成 CN / eea / GL 都返回同样的日志，因此请求不到日志时优先查加密与 v / c / zone。

device = 'mist'                          # 设备代号（对应表单 p）
code = device + '_eea_global'            # ROM code（对应表单 d），如 corot / air_global
version = 'OS3.0.305.0.WPUEUXM'          # 完整版本号
region = 'eea'                           # 区域：cn / global / eea / in / id / tw ...
locale = 'zh_TW'                         # 接口语种：zh_CN / zh_TW / en_US / ja_JP / ko_KR / ru_RU ...
zone = 2                                 # options.zone：照数据库 roms.zone 填（1=中国、2=国际），别按 region 推断

form = dict(common.HyperOSForm)
form['d'] = code
form['pn'] = code.split('_global')[0]
form['p'] = device
form['r'] = {'cn': 'CN', 'global': 'GL'}.get(region, region)
form['b'] = 'F'
form['c'] = '16.0'
form['sdk'] = common.sdk['16.0']
form['options'] = dict(form['options'], zone=zone, cv=version)
form['v'] = version
form['ov'] = version
form['l'] = locale

print(json.dumps({'d': form['d'], 'pn': form['pn'], 'p': form['p'], 'r': form['r'],
                  'zone': form['options']['zone'], 'l': form['l'], 'v': form['v']}, ensure_ascii=False))

encrypted_form = common.CryptoManager.encrypt(json.dumps(form))
logs = common.ChangelogManager.fetch(encrypted_form, device)
if logs:
    for name, log in logs.items():
        print(f'--- {name} ---')
        common.ChangelogManager.print_log(log or {})
else:
    print('接口没有返回更新日志（应答里的 Code / patchInfo 可用于排查 code、版本、区域是否匹配）')
