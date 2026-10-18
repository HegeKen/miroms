"""
miroms.local_mt - LM Studio 本地翻译客户端（原生 /api/v1/chat）

面向 Tencent Hunyuan-MT-7B（LM Studio 加载 GGUF）。它是**纯翻译模型**：

* 官方没有 system prompt，提示词按模型卡模板拼接：

    ZH<=>XX：``把下面的文本翻译成<目标语言>，不要额外解释。``
    XX<=>XX：``Translate the following segment into <target>, without additional explanation.``

* 默认走 LM Studio 原生接口（0.4+）::

    POST http://127.0.0.1:1234/api/v1/chat
    {"model": "tencent.hunyuan-mt-7b",
     "system_prompt": "把下面的文本翻译成简体中文，不要额外解释。",
     "input": "What is your favorite color?"}

  提示词放在 ``system_prompt``、源文本放在 ``input``；返回
  ``{"output": [{"type": "message", "content": ...}], "stats": {...}}``。

* 也可以 ``--api openai`` 改走 OpenAI 兼容的 ``/v1/chat/completions``。

* 返回的是纯译文而不是 JSON，因此这里不做 JSON 解析，改由
  :func:`validate_translation` 校验占位符 / 语种 / 长度。

    client = LocalMTClient.from_config()
    client.model = client.resolve_model()
    text = client.translate('优化系统稳定性', 'German', source_is_chinese=True)

依赖：标准库 urllib（与 miroms.deepseek 一致），不引入 requests。
"""
import json
import os
import re
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

# logs 语言列 -> Hunyuan-MT 认识的目标语言名（模型卡 Supported languages）
LANG_TARGETS: Dict[str, str] = {
	'logs_zh': 'Chinese',
	'logs_zh_tw': 'Traditional Chinese',
	'logs_en': 'English',
	'logs_ja': 'Japanese',
	'logs_ko': 'Korean',
	'logs_ru': 'Russian',
	'logs_uk': 'Ukrainian',
	'logs_pl': 'Polish',
	'logs_de': 'German',
	'logs_fr': 'French',
	'logs_it': 'Italian',
	'logs_es': 'Spanish',
	'logs_pt': 'Portuguese',
	'logs_tr': 'Turkish',
	'logs_id': 'Indonesian',
	'logs_vi': 'Vietnamese',
	'logs_th': 'Thai',
	'logs_ar': 'Arabic',
	'logs_in': 'Hindi',
	'logs_ug': 'Uyghur',
	'logs_bo': 'Tibetan',
}

ZH_COLUMN = 'logs_zh'
EN_COLUMN = 'logs_en'
ZH_TW_COLUMN = 'logs_zh_tw'

# 中文（含繁体）目标：译文里必须有汉字；日文允许纯假名，不在此列。
HAN_TARGETS = frozenset({ZH_COLUMN, ZH_TW_COLUMN})
# 允许出现汉字的非中文目标（日文汉字、韩文偶用汉字）。
HAN_ALLOWED_TARGETS = frozenset({ZH_COLUMN, ZH_TW_COLUMN, 'logs_ja', 'logs_ko'})

ZH_INSTRUCTION = '把下面的文本翻译成{target}，不要额外解释。'
EN_INSTRUCTION = 'Translate the following segment into {target}, without additional explanation.'

API_NATIVE = 'native'
API_OPENAI = 'openai'
DEFAULT_BASE_URL = 'http://127.0.0.1:1234'
DEFAULT_MODEL = 'hunyuan-mt-7b'

# 占位符：%s / %1$s / %d / {0} / {name} / ${var}
PLACEHOLDER_RE = re.compile(r'%(\d+\$)?[-+ 0#]*\d*(?:\.\d+)?[sd@]|\{[^{}]*\}|\$\{[^{}]*\}')
HAN_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

# 目标语言的特征文字区间：译文一个都不命中即视为译错语言（英文回落 / 未翻译）
SCRIPT_RANGES = {
	'logs_ru': ((0x0400, 0x04FF),),
	'logs_uk': ((0x0400, 0x04FF),),
	'logs_ar': ((0x0600, 0x06FF),),
	'logs_ug': ((0x0600, 0x06FF),),
	'logs_bo': ((0x0F00, 0x0FFF),),
	'logs_th': ((0x0E00, 0x0E7F),),
	'logs_in': ((0x0900, 0x097F),),
	'logs_ja': ((0x3040, 0x30FF), (0x4E00, 0x9FFF)),
	'logs_ko': ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x4E00, 0x9FFF)),
}

_PROMPT_ECHO = (
	'不要额外解释', '翻译成', 'translate the following', 'without additional explanation',
)


class LocalMTError(RuntimeError):
	"""LM Studio 调用失败（连不上 / HTTP 错误 / 返回结构异常）"""


def normalize_base_url(base_url: Optional[str] = None) -> Tuple[str, Optional[str]]:
	"""归一化 LM Studio 地址，并推断接口模式。

	http://127.0.0.1:1234/api/v1  -> ('http://127.0.0.1:1234', 'native')
	http://127.0.0.1:1234/v1      -> ('http://127.0.0.1:1234', 'openai')
	http://127.0.0.1:1234         -> ('http://127.0.0.1:1234', None)
	"""
	value = str(base_url or DEFAULT_BASE_URL).strip().rstrip('/')
	api: Optional[str] = None
	for suffix, mode in (('/api/v1', API_NATIVE), ('/v1', API_OPENAI)):
		if value.lower().endswith(suffix):
			value = value[:-len(suffix)].rstrip('/')
			api = mode
			break
	return value or DEFAULT_BASE_URL, api


def has_han(text: Any) -> bool:
	return bool(HAN_RE.search(str(text or '')))


def build_instruction(target_language: str, source_is_chinese: bool = False) -> str:
	"""按 Hunyuan-MT 官方模板生成翻译指令（中英方向用中文指令，其余用英文指令）"""
	template = (ZH_INSTRUCTION if (source_is_chinese or target_language in ('Chinese', 'Traditional Chinese'))
				else EN_INSTRUCTION)
	return template.format(target=target_language)


def clean_output(text: Any) -> str:
	"""清理模型输出：去代码块 / 包裹引号 / 常见前缀"""
	value = str(text or '').strip()
	if value.startswith('```'):
		lines = value.splitlines()
		if lines and lines[0].startswith('```'):
			lines = lines[1:]
		if lines and lines[-1].strip() == '```':
			lines = lines[:-1]
		value = '\n'.join(lines).strip()
	if len(value) > 1 and value[0] in ('"', "'", '“', '「') and value[-1] in ('"', "'", '”', '」'):
		value = value[1:-1].strip()
	for prefix in ('译文：', '译文:', '翻译：', '翻译:', 'Translation:', 'Translated text:'):
		if value.lower().startswith(prefix.lower()):
			value = value[len(prefix):].strip()
	return value


def placeholders(text: Any) -> Counter:
	return Counter(PLACEHOLDER_RE.findall(str(text or '')))


def similarity(left: Any, right: Any) -> float:
	"""译文相似度（NFKC + casefold，忽略空白与标点），用于「重译 vs 现有译文」比较"""
	def normalize(value: Any) -> str:
		text = unicodedata.normalize('NFKC', str(value or '')).casefold()
		return re.sub(r'[\s\W_]+', '', text, flags=re.UNICODE)

	a, b = normalize(left), normalize(right)
	if not a or not b:
		return 0.0
	return SequenceMatcher(None, a, b).ratio()


def in_target_script(text: Any, column: str) -> bool:
	"""译文是否命中目标语言的特征文字（未配置区间的语言返回 True）"""
	ranges = SCRIPT_RANGES.get(column)
	if not ranges:
		return True
	for char in str(text or ''):
		code = ord(char)
		if any(start <= code <= end for start, end in ranges):
			return True
	return False


def script_issue(text: Any, column: str) -> Optional[str]:
	"""现有译文的脚本检查：错列（汉字混入）或整段英文回落"""
	value = str(text or '')
	if not value or column in HAN_ALLOWED_TARGETS:
		return None
	if has_han(value):
		return 'contains_han'
	if column in SCRIPT_RANGES and len(value.strip()) >= 4 and not in_target_script(value, column):
		return 'wrong_script'
	return None


def validate_translation(source: str, output: str, column: str) -> Tuple[bool, str]:
	"""校验模型译文，返回 (是否可用, 原因)；不可用时原因写入报告"""
	if not output:
		return False, 'empty'
	lower = output.lower()
	for marker in _PROMPT_ECHO:
		if marker in lower:
			return False, 'prompt_echo'
	if placeholders(source) != placeholders(output):
		return False, 'placeholder_mismatch'
	if len(output) > max(200, len(source) * 8):
		return False, 'too_long'
	if column not in HAN_ALLOWED_TARGETS and has_han(output):
		return False, 'contains_han'
	if column in HAN_TARGETS and has_han(source) and not has_han(output):
		return False, 'missing_han'
	if has_han(source) and column in SCRIPT_RANGES and not in_target_script(output, column):
		return False, 'wrong_script'
	return True, ''


class LocalMTClient:
	"""LM Studio 翻译客户端（原生 /api/v1/chat，或 OpenAI 兼容 /v1/chat/completions）"""

	DEFAULT_BASE_URL = DEFAULT_BASE_URL
	DEFAULT_MODEL = DEFAULT_MODEL

	def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None,
				 timeout: float = 120, max_retries: int = 2,
				 temperature: float = 0.7, top_p: float = 0.6,
				 max_tokens: int = 0, top_k: Optional[int] = None,
				 repeat_penalty: Optional[float] = None,
				 api: Optional[str] = None) -> None:
		self.base_url, inferred_api = normalize_base_url(base_url)
		self.api = str(api or inferred_api or API_NATIVE).lower()
		if self.api not in (API_NATIVE, API_OPENAI):
			raise ValueError(f'未知接口模式 {api!r}，可选：{API_NATIVE} / {API_OPENAI}')
		self.model = (model or '').strip()
		self.timeout = float(timeout)
		self.max_retries = max(0, int(max_retries))
		self.temperature = float(temperature)
		self.top_p = float(top_p)
		self.max_tokens = int(max_tokens or 0)
		# 模型卡推荐 top_k=20 / repetition_penalty=1.05；LM Studio 默认即可，显式传参时才带上
		self.top_k = int(top_k) if top_k else None
		self.repeat_penalty = float(repeat_penalty) if repeat_penalty else None
		self.calls = 0
		self.last_usage: Dict[str, Any] = {}
		self._lock = threading.Lock()

	@classmethod
	def from_config(cls, model: Optional[str] = None, **kwargs: Any) -> 'LocalMTClient':
		"""按「命令行 > 环境变量 > config.py」读取配置（model 为空时自动探测）"""
		try:
			import config
		except ModuleNotFoundError:
			config = None
		base_url = (kwargs.pop('base_url', None)
					or os.environ.get('LMSTUDIO_BASE_URL')
					or getattr(config, 'lmstudio_base_url', None)
					or cls.DEFAULT_BASE_URL)
		model = (model or os.environ.get('LMSTUDIO_MODEL')
				 or getattr(config, 'lmstudio_model', None) or '')
		api = (kwargs.pop('api', None)
			   or os.environ.get('LMSTUDIO_API')
			   or getattr(config, 'lmstudio_api', None) or '')
		timeout = kwargs.pop('timeout', None) or os.environ.get('LMSTUDIO_TIMEOUT') \
			or getattr(config, 'lmstudio_timeout', 120)
		return cls(base_url=base_url, model=model, timeout=float(timeout),
				   api=api or None, **kwargs)

	def _ssl_context(self) -> ssl.SSLContext:
		"""https 端点用 certifi 兜底（框架版 Python 常缺系统根证书）"""
		try:
			import certifi
		except ImportError:
			return ssl.create_default_context()
		return ssl.create_default_context(cafile=certifi.where())

	def _url(self, path: str) -> str:
		return f'{self.base_url}/{path.lstrip("/")}'

	def _endpoint(self, path: str) -> str:
		"""按接口模式拼端点：native -> /api/v1/…，openai -> /v1/…"""
		prefix = 'api/v1' if self.api == API_NATIVE else 'v1'
		return self._url(f'{prefix}/{path.lstrip("/")}')

	def list_models(self) -> List[str]:
		"""GET 模型列表；原生接口取已加载实例 id，OpenAI 兼容取模型 id"""
		url = self._endpoint('models')
		request = urllib.request.Request(url, method='GET',
										 headers={'Accept': 'application/json'})
		try:
			with urllib.request.urlopen(request, timeout=self.timeout,
										context=self._ssl_context()) as response:
				payload = json.loads(response.read().decode('utf-8'))
		except urllib.error.HTTPError as error:
			detail = error.read().decode('utf-8', 'replace')[:200]
			raise LocalMTError(f'GET {url} 失败: HTTP {error.code} {detail}') from error
		except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
			raise LocalMTError(
				f'连不上 LM Studio（{url}）：{error}；'
				f'请确认本地服务已启动（LM Studio → Developer → Start Server）') from error
		if self.api == API_NATIVE:
			models = payload.get('models') if isinstance(payload, dict) else None
			loaded_names: List[str] = []
			all_names: List[str] = []
			for item in models or []:
				if not isinstance(item, dict):
					continue
				if item.get('key'):
					all_names.append(str(item['key']))
				loaded = [str(instance.get('id')) for instance in item.get('loaded_instances') or []
						  if isinstance(instance, dict) and instance.get('id')]
				loaded_names.extend(loaded)
			return loaded_names or all_names
		data = payload.get('data') if isinstance(payload, dict) else None
		if not isinstance(data, list):
			return []
		return [str(item.get('id')) for item in data
				if isinstance(item, dict) and item.get('id')]

	def resolve_model(self) -> str:
		"""确定模型 id：显式配置 > 名称含 hunyuan 的模型 > 唯一模型"""
		if self.model:
			return self.model
		models = self.list_models()
		if not models:
			raise LocalMTError('LM Studio 没有已加载的模型，请先在 LM Studio 里加载 Hunyuan-MT-7B')
		hunyuan = [name for name in models if 'hunyuan' in name.lower() or 'mt-7b' in name.lower()]
		if len(hunyuan) == 1:
			self.model = hunyuan[0]
			return self.model
		if len(models) == 1:
			self.model = models[0]
			return self.model
		raise LocalMTError(
			f'无法自动确定模型，候选：{models}；请用 --model 指定（LM Studio 的模型标识）')

	def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
		body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
		last_error = ''
		for attempt in range(self.max_retries + 1):
			request = urllib.request.Request(url, data=body, method='POST', headers={
				'Content-Type': 'application/json',
				'Accept': 'application/json',
			})
			try:
				with urllib.request.urlopen(request, timeout=self.timeout,
											context=self._ssl_context()) as response:
					return json.loads(response.read().decode('utf-8'))
			except urllib.error.HTTPError as error:
				detail = error.read().decode('utf-8', 'replace')[:300]
				last_error = f'HTTP {error.code}: {detail}'
				if error.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
					time.sleep(2 ** (attempt + 1))
					continue
				raise LocalMTError(f'POST {url} 失败: {last_error}') from error
			except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
				last_error = f'{type(error).__name__}: {error}'
				if attempt < self.max_retries:
					time.sleep(2 ** (attempt + 1))
					continue
				raise LocalMTError(f'POST {url} 失败: {last_error}') from error
		raise LocalMTError(f'POST {url} 失败: {last_error}')

	def _max_tokens_for(self, text: str) -> int:
		if self.max_tokens:
			return self.max_tokens
		return max(512, min(4096, len(str(text or '')) * 3))

	def _parse_native(self, response: Dict[str, Any]) -> Tuple[str, bool]:
		"""解析原生接口：output 里取第一条 message，stop_reason 判断是否被截断"""
		for item in (response.get('output') if isinstance(response, dict) else None) or []:
			if isinstance(item, dict) and item.get('type') == 'message' \
					and isinstance(item.get('content'), str):
				reason = str((response.get('stats') or {}).get('stop_reason') or '').lower()
				return item['content'], ('max' in reason or 'length' in reason)
		raise LocalMTError(f'返回结构异常: {str(response)[:300]}')

	def _parse_openai(self, response: Dict[str, Any]) -> Tuple[str, bool]:
		"""解析 OpenAI 兼容接口：choices[0].message.content，finish_reason=length 表示截断"""
		try:
			choice = response['choices'][0]
			return choice['message']['content'], choice.get('finish_reason') == 'length'
		except (KeyError, IndexError, TypeError) as error:
			raise LocalMTError(f'返回结构异常: {str(response)[:300]}') from error

	def translate(self, text: str, target_language: str,
				  source_is_chinese: bool = False) -> str:
		"""把 text 翻译成 target_language，返回清理后的纯译文"""
		source = str(text or '').strip()
		if not source:
			raise LocalMTError('源文本为空')
		instruction = build_instruction(target_language, source_is_chinese)
		if self.api == API_NATIVE:
			path = 'chat'
			token_key = 'max_output_tokens'
			payload: Dict[str, Any] = {
				'model': self.model,
				'system_prompt': instruction,
				'input': source,
				'temperature': self.temperature,
				'top_p': self.top_p,
				token_key: self._max_tokens_for(source),
				'stream': False,
			}
		else:
			path = 'chat/completions'
			token_key = 'max_tokens'
			payload = {
				'model': self.model,
				'messages': [{'role': 'user', 'content': f'{instruction}\n\n{source}'}],
				'temperature': self.temperature,
				'top_p': self.top_p,
				token_key: self._max_tokens_for(source),
				'stream': False,
			}
		if self.top_k:
			payload['top_k'] = self.top_k
		if self.repeat_penalty:
			payload['repeat_penalty'] = self.repeat_penalty
		url = self._endpoint(path)
		for attempt in range(2):
			response = self._post(url, payload)
			if self.api == API_NATIVE:
				content, truncated = self._parse_native(response)
				usage = response.get('stats') or {}
			else:
				content, truncated = self._parse_openai(response)
				usage = response.get('usage') or {}
			with self._lock:
				self.calls += 1
				self.last_usage = usage
			if truncated and attempt == 0:
				payload[token_key] = min(8192, int(payload[token_key]) * 2)
				continue
			return clean_output(content)
		return ''
