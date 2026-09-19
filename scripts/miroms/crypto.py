import json
import base64
import urllib.parse
from typing import Dict, Union
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
		def encrypt(cls, json_request: Union[Dict, str]) -> str:
				"""AES-CBC加密并URL编码 (原: miui_encrypt)"""
				cipher = AES.new(_const.MIUI_KEY, AES.MODE_CBC, _const.MIUI_IV)
				text = str(json_request).encode("ascii")
				padded = pad(text, AES.block_size)
				# 必须真正执行 AES 加密：此前漏掉 cipher.encrypt()，只把「明文 + PKCS#7 填充」
				# 做了 base64，服务端解不出任何有效表单，只能回空的 patchInfo（Code 2000 success）。
				cipher_text = cipher.encrypt(padded)
				encrypted = base64.b64encode(cipher_text).decode("utf-8")
				return urllib.parse.quote(encrypted).replace("/", "%2F")
