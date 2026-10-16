"""
miroms - 小米 ROM 数据管理包

模块结构:
    constants   - 系统常量配置 (Constants, branches, HyperOSForm, CHANGELOG_LOCALES)
    data        - 设备数据常量 (fullDevices, currentStable, flags 等)
    utils       - 版本处理与文件操作工具 (VersionUtils, FileUtils)
    database    - 数据库管理 (DatabaseManager)
    crypto      - 加密解密管理 (CryptoManager)
    firmware    - 固件信息解析 (FirmwareParser)
    recorder    - 数据记录管理 (DataRecorder)
    network     - 网络请求客户端 (NetworkClient)
    changelog   - 更新日志管理 (ChangelogManager)
    logs_store  - 更新日志字典化存储 (LogStore)
    validator   - 数据校验 (DataValidator)
    exporters   - 数据导出 (exportV1, exportV2, exportV3)
    legacy_exporters - 参考站点附属导出 (api/v1 = NuxtMR、api/v2 = HyperOS.fans)
"""

from miroms.constants import (Constants, _const, branches, HyperOSForm,
	CHANGELOG_LOCALES, CHANGELOG_COLUMNS, CHANGELOG_EXTRA_COLUMNS, CHANGELOG_BASE_COLUMN,
	find_changelog_locale)
from miroms.data import (
	unreleased, currentStable, order, fullDevices, flags
)
from miroms.utils import VersionUtils, FileUtils
from miroms.database import DatabaseManager
from miroms.crypto import CryptoManager
from miroms.firmware import FirmwareParser
from miroms.recorder import DataRecorder
from miroms.network import NetworkClient
from miroms.changelog import ChangelogManager
from miroms.logs_store import LogStore
from miroms.validator import DataValidator
from miroms.exporters import exportV1, exportV2, exportV3, export_dev
from miroms.legacy_exporters import (
	export_sitelog, export_v1_extras, export_v2_extras, export_hub_extras,
	export_v1_index, export_v1_weekly_index, export_v1_weekly_weeks, export_v1_devlist,
	export_v2_index, export_v2_dev_index, export_v2_dev_weeks, export_v2_devices,
	export_hub_sitelog, export_tools,
)

__all__ = [
	# 常量
	'Constants', '_const', 'branches', 'HyperOSForm',
	'CHANGELOG_LOCALES', 'CHANGELOG_COLUMNS', 'CHANGELOG_EXTRA_COLUMNS', 'CHANGELOG_BASE_COLUMN',
	'find_changelog_locale',
	# 数据
	'unreleased', 'currentStable', 'order', 'fullDevices', 'flags',
	# 工具
	'VersionUtils', 'FileUtils',
	# 服务
	'DatabaseManager', 'CryptoManager',
	# 业务
	'FirmwareParser', 'DataRecorder', 'NetworkClient',
	'ChangelogManager', 'DataValidator', 'LogStore',
	# 导出
	'exportV1', 'exportV2', 'exportV3', 'export_dev',
	# 参考站点附属导出（api/v1 = NuxtMR、api/v2 = HyperOS.fans）
	'export_sitelog', 'export_v1_extras', 'export_v2_extras',
	'export_v1_index', 'export_v1_weekly_index', 'export_v1_weekly_weeks', 'export_v1_devlist',
	'export_v2_index', 'export_v2_dev_index', 'export_v2_dev_weeks', 'export_v2_devices',
	# hub 自身（api/v3）：站点日志 + 工具下载
	'export_hub_extras', 'export_hub_sitelog', 'export_tools',
]
