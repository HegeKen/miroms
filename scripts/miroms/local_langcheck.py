"""
miroms.local_langcheck - 用本地翻译模型校验译文是否使用了正确的语言

原理（回译不变性）：让模型把单元格文本翻译成它「本应使用的语言」。

* 文本本来就用该语言书写 -> 译文与原文高度一致；
* 文本其实是别的语言（英文回落、俄文混进乌克兰文列、简体混进繁体列）->
  译文与原文差异明显。

先用确定性规则挡掉一部分（文字体系不符 / 与 logs_en 完全相同 / 简繁转换），
其余（主要是拉丁字母语种）按批次交给本地 Hunyuan-MT：默认 16 条/次，
逐条算 similarity，低于阈值判为语言不符。

产出的 issue 结构可直接写入 ``logs.lang_issues``::

    {"logs_de": {"detected": "英语", "confidence": 0.93,
                 "reason": "回译相似度 0.29 < 0.62（疑似英语）",
                 "ratio": 0.29, "source": "local-mt"}}
"""
import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.local_mt import (
	LANG_TARGETS,
	LocalMTClient,
	LocalMTError,
	has_han,
	script_issue,
	similarity,
)

# 语言列 -> 中文名（写进 lang_issues.detected）
LANG_LABELS: Dict[str, str] = {
	'logs_zh': '简体中文',
	'logs_zh_tw': '繁体中文',
	'logs_en': '英语',
	'logs_ja': '日语',
	'logs_ko': '韩语',
	'logs_ru': '俄语',
	'logs_uk': '乌克兰语',
	'logs_pl': '波兰语',
	'logs_de': '德语',
	'logs_fr': '法语',
	'logs_it': '意大利语',
	'logs_es': '西班牙语',
	'logs_pt': '葡萄牙语',
	'logs_tr': '土耳其语',
	'logs_id': '印尼语',
	'logs_vi': '越南语',
	'logs_th': '泰语',
	'logs_ar': '阿拉伯语',
	'logs_in': '印地语',
	'logs_ug': '维吾尔语',
	'logs_bo': '藏语',
}

DEFAULT_LONG_RATIO = 0.62
DEFAULT_SHORT_RATIO = 0.45
SHORT_CHARS = 12
MIN_CHARS = 2

UK_CHARS = frozenset('іїєґІЇЄҐ')
RU_CHARS = frozenset('ыэёъЫЭЁЪ')

try:  # 简繁转换只用于 zh_tw 的规则检查，缺依赖时退回模型判断
	from opencc import OpenCC

	_S2T = OpenCC('s2t')
except Exception:  # noqa: BLE001 - 可选依赖
	_S2T = None


def lang_label(column: str) -> str:
	return LANG_LABELS.get(column, column)


def normalize(value: Any) -> str:
	text = unicodedata.normalize('NFKC', str(value or '')).casefold()
	return re.sub(r'[\s\W_]+', '', text, flags=re.UNICODE)


def is_trivial(text: Any) -> bool:
	"""纯数字 / 标点 / 单字符不参与语言判断（模型无法可靠识别）"""
	value = str(text or '').strip()
	if len(value) < MIN_CHARS:
		return True
	return not re.search(r'[^\W\d_]', value, flags=re.UNICODE)


def detect_language(text: Any) -> str:
	"""粗粒度文字体系判断，仅用于 issue 的 detected 字段"""
	value = str(text or '')
	if re.search(r'[\u3040-\u30ff]', value):
		return '日语'
	if re.search(r'[\uac00-\ud7af]', value):
		return '韩语'
	if re.search(r'[\u0e00-\u0e7f]', value):
		return '泰语'
	if re.search(r'[\u0900-\u097f]', value):
		return '印地语'
	if re.search(r'[\u0f00-\u0fff]', value):
		return '藏语'
	if re.search(r'[\u0600-\u06ff]', value):
		return '阿拉伯语系'
	if re.search(r'[\u0400-\u04ff]', value):
		return '乌克兰语' if any(char in UK_CHARS for char in value) else '俄语'
	if has_han(value):
		return '中文'
	if re.search(r'[A-Za-z]', value):
		return '英语/拉丁字母'
	return '未知'


def simplified_ratio(text: Any) -> float:
	"""文本中「简体 -> 繁体」会被改写的字符占比（0 表示本来就是繁体）"""
	if not _S2T:
		return 0.0
	value = str(text or '')
	if not value:
		return 0.0
	converted = _S2T.convert(value)
	if converted == value:
		return 0.0
	changed = sum(1 for left, right in zip(value, converted) if left != right)
	return changed / max(1, len(value))


def numbered_input(texts: Sequence[str]) -> str:
	return '\n'.join(f'{index + 1}. {str(text).replace(chr(10), " ").strip()}'
					 for index, text in enumerate(texts))


NUMBERED_RE = re.compile(r'^\s*(\d+)\s*[.、)]\s*(.*)$')


def parse_numbered(output: str, count: int) -> List[str]:
	"""解析「1. xxx」编号行；数量/编号不齐时返回 [] 让调用方回退"""
	items: Dict[int, str] = {}
	for line in str(output or '').splitlines():
		match = NUMBERED_RE.match(line)
		if not match:
			continue
		index = int(match.group(1))
		if 1 <= index <= count:
			items[index] = match.group(2).strip()
	if len(items) != count:
		return []
	return [items[index] for index in range(1, count + 1)]


def threshold_for(text: str, long_ratio: float, short_ratio: float,
				  short_chars: int = SHORT_CHARS) -> float:
	return short_ratio if len(str(text or '')) <= short_chars else long_ratio


def cell_key(column: str, text: str) -> str:
	digest = hashlib.sha1(f'{column}\x00{text}'.encode('utf-8')).hexdigest()
	return f'{column}:{digest}'


def rule_issue(column: str, text: str, en_text: str) -> Optional[Dict[str, Any]]:
	"""不调用模型的确定性检查"""
	value = str(text or '').strip()
	han = sum(1 for char in value if '\u4e00' <= char <= '\u9fff')
	# 只有汉字占主导才判「中文混入」；译文里引用中文应用名（如「拼多多」）不算
	if column not in ('logs_zh', 'logs_zh_tw', 'logs_ja', 'logs_ko') \
			and han >= 4 and han / max(1, len(value)) >= 0.5:
		return {'detected': '中文', 'confidence': 0.95,
				'reason': '该列以汉字为主，不是目标语言的正常写法',
				'source': 'rule:script'}
	issue = script_issue(value, column)
	if issue == 'wrong_script':
		return {'detected': detect_language(value), 'confidence': 0.95,
				'reason': f'文字体系与「{lang_label(column)}」不符',
				'source': 'rule:script'}

	if column != 'logs_en' and len(value) >= 8 and en_text:
		if normalize(value) == normalize(en_text):
			return {'detected': '英语', 'confidence': 0.9,
					'reason': '与 logs_en 完全相同（英文回落）',
					'source': 'rule:fallback'}

	if column == 'logs_zh_tw':
		ratio = simplified_ratio(value)
		if ratio >= 0.06:
			return {'detected': '简体中文', 'confidence': 0.9,
					'reason': f'简繁转换改写比例 {ratio:.2f}（疑似简体）',
					'ratio': round(ratio, 3), 'source': 'rule:opencc'}

	if column == 'logs_ru' and any(char in UK_CHARS for char in value):
		return {'detected': '乌克兰语', 'confidence': 0.9,
				'reason': '俄语列出现乌克兰语特有字母（і/ї/є/ґ）',
				'source': 'rule:script'}
	if column == 'logs_uk' and any(char in RU_CHARS for char in value) \
			and not any(char in UK_CHARS for char in value):
		return {'detected': '俄语', 'confidence': 0.9,
				'reason': '乌克兰语列出现俄语特有字母（ы/э/ё/ъ）',
				'source': 'rule:script'}
	return None


# ==================== 本地语种识别（fastText lid.176） ====================

import os
from pathlib import Path

DETECTOR_MAP = {
	'en': 'logs_en', 'de': 'logs_de', 'fr': 'logs_fr', 'es': 'logs_es',
	'pt': 'logs_pt', 'it': 'logs_it', 'pl': 'logs_pl', 'ru': 'logs_ru',
	'uk': 'logs_uk', 'ja': 'logs_ja', 'ko': 'logs_ko', 'zh': 'logs_zh',
	'ar': 'logs_ar', 'hi': 'logs_in', 'th': 'logs_th', 'vi': 'logs_vi',
	'id': 'logs_id', 'tr': 'logs_tr', 'ug': 'logs_ug', 'bo': 'logs_bo',
}

DETECT_MIN_CHARS = 6
DETECT_PROB = 0.95
DETECT_PROB_EN_SINGLE = 0.75

_FASTTEXT_MODEL = None
_FASTTEXT_TRIED = False


def fasttext_model():
	"""懒加载 fastText lid.176 模型；路径可用 LANGID_MODEL 覆盖"""
	global _FASTTEXT_MODEL, _FASTTEXT_TRIED
	if _FASTTEXT_TRIED:
		return _FASTTEXT_MODEL
	_FASTTEXT_TRIED = True
	path = os.environ.get('LANGID_MODEL') or str(Path.home() / '.cache/langid/lid.176.ftz')
	if not Path(path).exists():
		return None
	try:
		import fasttext

		_FASTTEXT_MODEL = fasttext.load_model(path)
	except Exception:  # noqa: BLE001 - 模型缺失时降级为规则
		_FASTTEXT_MODEL = None
	return _FASTTEXT_MODEL


def detector_issue(column: str, text: str) -> Optional[Dict[str, Any]]:
	"""本地语种模型判断：文本实际语言与列语言不一致时返回 issue

	只在高置信度时判定，避免短 UI 词（Asystent online 之类）误报。
	"""
	value = str(text or '').strip()
	# 维吾尔/藏文与阿拉伯文同属阿拉伯字母体系，模型容易互判，交给 script 规则
	if column in ('logs_zh', 'logs_zh_tw', 'logs_ug', 'logs_bo'):
		return None
	if len(value) < DETECT_MIN_CHARS:
		return None
	model = fasttext_model()
	if model is None:
		return None
	try:
		result = model.f.predict(value.replace('\n', ' '), 1, 0.0, 'strict')[0]
	except Exception:  # noqa: BLE001
		return None
	code = str(result[1]).replace('__label__', '')
	prob = float(result[0])
	if column == 'logs_ar' and code in ('fa', 'ur', 'ps', 'sd'):
		return None
	target = DETECTOR_MAP.get(code)
	if not target or target == column:
		return None
	# 日/韩里出现汉字是正常现象
	if column in ('logs_ja', 'logs_ko') and target == 'logs_zh':
		return None
	single = ' ' not in value
	limit = DETECT_PROB_EN_SINGLE if (single and target == 'logs_en') else DETECT_PROB
	if prob < limit:
		return None
	return {'detected': lang_label(target), 'confidence': round(min(0.95, 0.6 + prob / 3), 2),
			'reason': f'fastText 判为{lang_label(target)}（置信度 {prob:.2f}，'
					  f'目标语言 {lang_label(column)}）',
			'ratio': round(prob, 3), 'source': 'detector:fasttext'}


class LangChecker:
	"""批量语言校验（规则 + 本地模型回译）"""

	def __init__(self, client: LocalMTClient, long_ratio: float = DEFAULT_LONG_RATIO,
				 short_ratio: float = DEFAULT_SHORT_RATIO, short_chars: int = SHORT_CHARS,
				 batch_size: int = 16, workers: int = 2,
				 cache: Optional[Dict[str, str]] = None) -> None:
		self.client = client
		self.long_ratio = float(long_ratio)
		self.short_ratio = float(short_ratio)
		self.short_chars = int(short_chars)
		self.batch_size = max(1, int(batch_size))
		self.workers = max(1, int(workers))
		self.cache = cache if isinstance(cache, dict) else {}

	# ---------- 单条 / 批量 ----------

	def check_text(self, column: str, text: str) -> Tuple[Optional[str], float]:
		"""返回 (译文, 相似度)；失败时译文为 None"""
		key = cell_key(column, text)
		cached = self.cache.get(key)
		if isinstance(cached, str) and cached:
			return cached, similarity(text, cached)
		output = self.client.translate(
			text, LANG_TARGETS[column], source_is_chinese=has_han(text))
		if not output:
			return None, 0.0
		self.cache[key] = output
		return output, similarity(text, output)

	def check_batch(self, column: str, texts: Sequence[str]) -> List[Tuple[Optional[str], float]]:
		"""一批同语言文本 -> [(译文, 相似度)]；批量解析失败时逐条回退"""
		pending = []
		results: List[Optional[Tuple[Optional[str], float]]] = [None] * len(texts)
		for index, text in enumerate(texts):
			cached = self.cache.get(cell_key(column, text))
			if isinstance(cached, str) and cached:
				results[index] = (cached, similarity(text, cached))
			else:
				pending.append(index)
		if not pending:
			return [item or (None, 0.0) for item in results]

		lines = [texts[index] for index in pending]
		outputs: List[str] = []
		if len(lines) > 1:
			outputs = self.client.translate_lines(
				lines, LANG_TARGETS[column],
				source_is_chinese=has_han(lines[0]))
		if not outputs or len(outputs) != len(lines):
			outputs = []
			for line in lines:
				try:
					outputs.append(self.client.translate(
						line, LANG_TARGETS[column], source_is_chinese=has_han(line)))
				except LocalMTError:
					outputs.append('')
		for slot, index in enumerate(pending):
			text, output = texts[index], outputs[slot] if slot < len(outputs) else ''
			if output:
				self.cache[cell_key(column, text)] = output
			results[index] = (output or None, similarity(text, output) if output else 0.0)
		return [item or (None, 0.0) for item in results]

	def classify(self, column: str, text: str, output: Optional[str], ratio: float) -> Optional[Dict[str, Any]]:
		if not output:
			return None
		limit = threshold_for(text, self.long_ratio, self.short_ratio, self.short_chars)
		if ratio >= limit:
			return None
		confidence = round(min(0.95, 0.6 + (limit - ratio) * 0.8), 2)
		return {'detected': detect_language(text), 'confidence': confidence,
				'reason': f'回译相似度 {ratio:.2f} < {limit:.2f}（疑似{detect_language(text)}）',
				'ratio': round(ratio, 3), 'source': 'local-mt'}
