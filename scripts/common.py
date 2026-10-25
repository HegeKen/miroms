"""
common.py - 向后兼容入口模块

此模块将 miroms 包中的所有公共 API 重新导出，
使现有的 `import common` 代码无需修改即可继续工作。

注意: fullDevices, currentStable, flags 变量保留为模块级赋值，
以便 sync_devices.py 可以通过正则替换来更新它们。
"""
from miroms.constants import (Constants, _const, branches, HyperOSForm,
	CHANGELOG_LOCALES, CHANGELOG_COLUMNS, CHANGELOG_EXTRA_COLUMNS, CHANGELOG_BASE_COLUMN,
	find_changelog_locale)
from miroms.utils import VersionUtils, FileUtils
from miroms.database import DatabaseManager
from miroms.crypto import CryptoManager
from miroms.firmware import FirmwareParser
from miroms.recorder import DataRecorder
from miroms.network import NetworkClient
from miroms.changelog import ChangelogManager
from miroms.xms import XmsStore
from miroms.logs_store import LogStore
from miroms.logs_text import LogText
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_proofread import LogProofreader
from miroms.logs_lang_fix import LogLangFixer
from miroms.logs_fill import LogFiller
from miroms.logs_clean import LogPrefixCleaner
from miroms.logs_restore import LogEscapeRestorer
from miroms.logs_mixed import MixedTranslationFixer
from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.validator import DataValidator
from miroms.exporters import (exportV1, exportV2, exportV3, export_series_index, export_statistics,
	export_dev, export_xms, load_series_data)
# 参考站点附属导出（api/v1 = NuxtMR、api/v2 = HyperOS.fans）
from miroms.legacy_exporters import (export_sitelog, export_v1_extras, export_v2_extras, export_hub_extras,
	export_v1_index, export_v1_weekly_index, export_v1_weekly_weeks, export_v1_devlist,
	export_v2_index, export_v2_dev_index, export_v2_dev_weeks, export_v2_devices,
	export_hub_sitelog, export_tools)
import logging

logger = logging.getLogger(__name__)

# ==================== 数据常量（保留模块级赋值供 sync_devices.py 重写） ====================
from miroms.data import unreleased, currentStable, order, fullDevices, flags

# sdk 别名保持兼容
sdk = _const.SDK_VERSIONS
