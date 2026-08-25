"""
common.py - 向后兼容入口模块

此模块将 miroms 包中的所有公共 API 重新导出，
使现有的 `import common` 代码无需修改即可继续工作。

注意: fullDevices, currentStable, flags 变量保留为模块级赋值，
以便 sync_devices.py 可以通过正则替换来更新它们。
"""
from miroms.constants import Constants, _const, branches, HyperOSForm
from miroms.utils import VersionUtils, FileUtils
from miroms.database import DatabaseManager
from miroms.crypto import CryptoManager
from miroms.firmware import FirmwareParser
from miroms.recorder import DataRecorder
from miroms.network import NetworkClient
from miroms.changelog import ChangelogManager
from miroms.validator import DataValidator
from miroms.exporters import exportV1, exportV2, exportV3, export_series_index, load_series_data
import logging

logger = logging.getLogger(__name__)

# ==================== 数据常量（保留模块级赋值供 sync_devices.py 重写） ====================
from miroms.data import unreleased, currentStable, order, fullDevices, flags

# sdk 别名保持兼容
sdk = _const.SDK_VERSIONS
