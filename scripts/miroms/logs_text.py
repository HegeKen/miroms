"""
miroms.logs_text - 日志文本判定与繁简转换

把「这段文字是不是中文 / 能不能直接当简体中文用 / 繁体怎么转简体」这些判定
从维护脚本里抽出来，供 LogStore、LogMaintenance 与各 CLI 共用。

典型用法：
    LogText.is_chinese('设置')            # True（有汉字且无假名）
    LogText.is_chinese('設定する')        # False（含日文假名）
    LogText.looks_simplified('优化系统', {'logs_en': 'Optimize system'})
    LogText.to_simplified('設定')         # '设定'（需 zhconv 或 opencc）
"""
import re
from typing import Callable, Dict, Optional, Tuple


class LogText:
	"""日志文本判定工具（全部为类方法，无需实例化）"""

	# 汉字（含扩展 A / 兼容区）；日文假名单独判断
	CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
	KANA_RE = re.compile(r'[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]')

	# 只用于「判断是不是简体」的常见繁体字；不做转换，只避免把繁体 / 日文误当简体
	TRADITIONAL_MARKERS = set(
		'這個發為說時會對開關網電話優復穩測試頁圖標設應聲視頻冊藍們麼樣讓覺點現實際軟體檔該還進過來與'
		'專業務員動態勢區醫藥學習練龍鳳萬億歲歡樂愛戀願認識語讀寫聽聞問題'
	)
	SIMPLIFIED_MARKERS = set(
		'这个发为说时会对开关网电话优复稳测试页图标设应声视频册蓝们么样让觉点现实际软体档该还进过来与'
		'专业务员动态势区医药学习练龙凤万亿岁欢乐爱恋愿认识语读写听闻问题'
	)

	_converter: Optional[Tuple[str, Callable[[str], str]]] = None
	_converter_checked = False

	@staticmethod
	def normalize(text) -> str:
		"""文本归一化：去掉首尾空白（与 LogStore.normalize 保持一致）"""
		return str(text if text is not None else '').strip()

	@classmethod
	def has_cjk(cls, text) -> bool:
		"""是否包含汉字"""
		return bool(text) and bool(cls.CJK_RE.search(str(text)))

	@classmethod
	def has_kana(cls, text) -> bool:
		"""是否包含日文假名"""
		return bool(text) and bool(cls.KANA_RE.search(str(text)))

	@classmethod
	def is_chinese(cls, text) -> bool:
		"""是否是可用的中文文本：有汉字且不含日文假名（不区分简繁）"""
		value = cls.normalize(text)
		return bool(value) and bool(cls.CJK_RE.search(value)) and not cls.KANA_RE.search(value)

	# 旧脚本里的命名，保留别名
	is_zh_ok = is_chinese

	@classmethod
	def looks_simplified(cls, text, texts: Optional[Dict[str, str]] = None,
						  zh_column: str = 'logs_zh') -> bool:
		"""content 是否可以直接当作简体中文使用

		- 含假名 → 日文；与其它语言列完全相同 → 那就是那一门语言；
		- 命中繁体特征字且没有简体特征字 → 繁体。
		"""
		value = cls.normalize(text)
		if not value or not cls.has_cjk(value) or cls.has_kana(value):
			return False
		for column, other in (texts or {}).items():
			if column == zh_column or not other:
				continue
			if value == cls.normalize(other):
				return False
		traditional = sum(1 for char in value if char in cls.TRADITIONAL_MARKERS)
		simplified = sum(1 for char in value if char in cls.SIMPLIFIED_MARKERS)
		return simplified > 0 or traditional == 0

	@classmethod
	def converter(cls) -> Optional[Tuple[str, Callable[[str], str]]]:
		"""返回 (库名, 繁转简函数)；zhconv / opencc 都没安装时返回 None"""
		if cls._converter_checked:
			return cls._converter
		cls._converter_checked = True
		try:
			import zhconv
			cls._converter = ('zhconv', lambda text: zhconv.convert(text, 'zh-cn'))
			return cls._converter
		except ImportError:
			pass
		try:
			from opencc import OpenCC
			converter = OpenCC('t2s')
			cls._converter = ('opencc', converter.convert)
		except ImportError:
			cls._converter = None
		return cls._converter

	@classmethod
	def to_simplified(cls, text) -> Optional[str]:
		"""繁体转简体；文本为空 / 非中文 / 没有可用的转换库时返回 None"""
		value = cls.normalize(text)
		if not value or not cls.has_cjk(value) or cls.has_kana(value):
			return None
		found = cls.converter()
		if not found:
			return None
		try:
			return cls.normalize(found[1](value))
		except Exception:
			return None
