import json
import base64
import urllib.parse
from typing import Dict
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from miroms.constants import _const


class CryptoManager:
		"""
		MIUI API加密解密管理

		合并原函数:
		- miui_decrypt() -> decrypt()
		- miui_encrypt() -> encrypt()
		"""

		@classmethod
		def decrypt(cls, encrypted_response: str) -> Dict:
				"""AES-CBC解密 (原: miui_decrypt)"""
				cipher = AES.new(_const.MIUI_KEY, AES.MODE_CBC, _const.MIUI_IV)
				decrypted = cipher.decrypt(base64.b64decode(encrypted_response))
				plaintext = decrypted.decode("utf-8").strip()
				pos = plaintext.rfind("}")
				if pos != -1:
						plaintext = plaintext[:pos + 1]
				return json.loads(plaintext)

		@classmethod
		def encrypt(cls, json_request: Dict) -> str:
				"""AES-CBC加密并URL编码 (原: miui_encrypt)"""
				cipher = AES.new(_const.MIUI_KEY, AES.MODE_CBC, _const.MIUI_IV)
				text = str(json_request).encode("ascii")
				padded = pad(text, AES.block_size)
				encrypted = base64.b64encode(padded).decode("utf-8")
				return urllib.parse.quote(encrypted).replace("/", "%2F")
