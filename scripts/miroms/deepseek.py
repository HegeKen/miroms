"""
miroms.deepseek - DeepSeek Chat API 的最小客户端（仅用标准库）

用途：日志校对 / 补译。API key 优先取环境变量 `DEEPSEEK_API_KEY`，
其次取 `scripts/config.py` 的 `deepseek_api_key`（可在 config 里直接填）。

    client = DeepSeekClient.from_config()
    payload = client.json_chat([{'role': 'user', 'content': '...'}])

依赖：标准库 urllib；不引入 requests。所有调用都受 max_calls 限制，
避免批量校对时意外刷爆额度。
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class DeepSeekError(RuntimeError):
	"""DeepSeek 调用失败（网络 / HTTP / 返回格式）"""


def extract_json(text: str) -> Dict[str, Any]:
	"""从模型返回里提取 JSON 对象（容忍 ```json 代码块与前后说明文字）"""
	if not text:
		raise DeepSeekError('模型返回为空')
	value = text.strip()
	if value.startswith('```'):
		lines = value.splitlines()
		if lines and lines[0].startswith('```'):
			lines = lines[1:]
		if lines and lines[-1].strip() == '```':
			lines = lines[:-1]
		value = '\n'.join(lines).strip()
	try:
		parsed = json.loads(value)
	except json.JSONDecodeError:
		start, end = value.find('{'), value.rfind('}')
		if start < 0 or end <= start:
			raise DeepSeekError(f'模型返回不是 JSON: {text[:200]!r}')
		try:
			parsed = json.loads(value[start:end + 1])
		except json.JSONDecodeError as exc:
			raise DeepSeekError(f'模型返回不是 JSON: {text[:200]!r}') from exc
	if not isinstance(parsed, dict):
		raise DeepSeekError(f'模型返回不是 JSON 对象: {text[:200]!r}')
	return parsed


class DeepSeekClient:
	"""DeepSeek Chat Completions 客户端（同步、可选 JSON 模式）"""

	DEFAULT_BASE_URL = 'https://api.deepseek.com'
	DEFAULT_MODEL = 'deepseek-flash'

	def __init__(self, api_key: str, model: Optional[str] = None,
				 base_url: Optional[str] = None, timeout: float = 60,
				 max_calls: int = 200, ca_bundle: Optional[str] = None,
				 reasoning_effort: Optional[str] = None) -> None:
		if not api_key:
			raise DeepSeekError(
				'未配置 DeepSeek API key：请设置环境变量 DEEPSEEK_API_KEY，'
				'或填写 data/scripts/config.py 的 deepseek_api_key')
		self.api_key = api_key
		self.model = model or self.DEFAULT_MODEL
		self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip('/')
		self.timeout = timeout
		self.max_calls = max_calls
		self.ca_bundle = ca_bundle
		self.reasoning_effort = reasoning_effort
		self.calls = 0
		self.last_usage: Dict[str, Any] = {}

	@classmethod
	def from_config(cls, model: Optional[str] = None, max_calls: Optional[int] = None) -> 'DeepSeekClient':
		"""按「环境变量 > config.py」的顺序读取配置"""
		import config
		api_key = os.environ.get('DEEPSEEK_API_KEY') or getattr(config, 'deepseek_api_key', '')
		return cls(
			api_key=api_key,
			model=model or os.environ.get('DEEPSEEK_MODEL') or getattr(config, 'deepseek_model', None),
			base_url=os.environ.get('DEEPSEEK_BASE_URL') or getattr(config, 'deepseek_base_url', None),
			timeout=float(getattr(config, 'deepseek_timeout', 60)),
			max_calls=int(max_calls if max_calls is not None
						  else getattr(config, 'deepseek_max_calls', 200)),
			ca_bundle=getattr(config, 'deepseek_ca_bundle', None) or None,
			reasoning_effort=getattr(config, 'deepseek_reasoning_effort', None) or None,
		)

	def _ssl_context(self) -> ssl.SSLContext:
		"""构造 TLS 上下文：优先用 certifi 的 CA（框架版 Python 常缺系统根证书）"""
		if self.ca_bundle:
			return ssl.create_default_context(cafile=self.ca_bundle)
		try:
			import certifi
			return ssl.create_default_context(cafile=certifi.where())
		except ImportError:
			return ssl.create_default_context()

	def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
		url = f'{self.base_url}/chat/completions'
		body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
		request = urllib.request.Request(url, data=body, method='POST', headers={
			'Content-Type': 'application/json',
			'Authorization': f'Bearer {self.api_key}',
		})
		last_error: Optional[Exception] = None
		for attempt in range(3):
			try:
				with urllib.request.urlopen(request, timeout=self.timeout,
											context=self._ssl_context()) as response:
					return json.loads(response.read().decode('utf-8'))
			except urllib.error.HTTPError as exc:
				detail = ''
				try:
					detail = exc.read().decode('utf-8', 'replace')[:300]
				except Exception:
					pass
				last_error = DeepSeekError(f'HTTP {exc.code}: {detail}')
				if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
					time.sleep(2 ** (attempt + 1))
					continue
				raise last_error from exc
			except (urllib.error.URLError, TimeoutError, OSError) as exc:
				last_error = DeepSeekError(f'请求失败: {type(exc).__name__}: {exc}')
				if attempt < 2:
					time.sleep(2 ** (attempt + 1))
					continue
				raise last_error from exc
		raise last_error or DeepSeekError('请求失败')

	def chat(self, messages: List[Dict[str, str]], temperature: float = 0.0,
			 max_tokens: int = 8192, json_mode: bool = True) -> str:
		"""发一次对话请求，返回文本内容（受 max_calls 限制）"""
		if self.calls >= self.max_calls:
			raise DeepSeekError(f'已达到本次调用的上限 max_calls={self.max_calls}')
		payload: Dict[str, Any] = {
			'model': self.model,
			'messages': messages,
			'temperature': temperature,
			'max_tokens': max_tokens,
			'stream': False,
		}
		if json_mode:
			payload['response_format'] = {'type': 'json_object'}
		if self.reasoning_effort:
			payload['reasoning_effort'] = self.reasoning_effort
		response = self._request(payload)
		self.calls += 1
		self.last_usage = response.get('usage') or {}
		try:
			return response['choices'][0]['message']['content']
		except (KeyError, IndexError, TypeError) as exc:
			raise DeepSeekError(f'DeepSeek 返回结构异常: {str(response)[:300]}') from exc

	def json_chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
		"""要求模型输出 JSON，并解析成 dict

		推理模型在 max_tokens 用尽时可能返回空 content，这里自动放大预算重试一次。
		"""
		max_tokens = int(kwargs.pop('max_tokens', 8192))
		for attempt in range(2):
			content = self.chat(messages, max_tokens=max_tokens, **kwargs)
			try:
				return extract_json(content)
			except DeepSeekError:
				if attempt == 0:
					max_tokens = min(max_tokens * 2, 32768)
					continue
				raise
