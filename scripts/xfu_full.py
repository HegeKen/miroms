"""
核查本地 xmfirmwareupdater.github.io 项目中的 HTML 页面，
提取固件文件名并检查是否已收录到数据库。
来源: HyperOS.fans XfuFull.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

EXCLUDED_FILES = {
	'OS1.0.4.0.UNKCNXMmiui_VERMEER_OS1.0.4.0.UNKCNXM_c3235c755f_14.0.zip'
}

# HTML 页面目录（按需修改为本地路径）
TARGET_DIRECTORY = "../Sources/xmfirmwareupdater.github.io/pages/hyperos"
FILENAME_SPAN_ID = 'filename'


def detect_file_encoding(file_path: str) -> str | None:
	"""检测文件编码"""
	try:
		with open(file_path, 'rb') as f:
			raw_content = f.read()
		import chardet
		result = chardet.detect(raw_content)
		return result.get('encoding')
	except (IOError, OSError) as e:
		print(f"警告: 无法读取文件 {file_path}: {e}")
		return None


def extract_filenames_from_html(file_path: str, encoding: str) -> list[str]:
	"""从HTML文件中提取文件名"""
	try:
		with open(file_path, 'r', encoding=encoding, errors='replace') as f:
			content = f.read()
		from bs4 import BeautifulSoup
		soup = BeautifulSoup(content, 'lxml')
		span_tags = soup.find_all('span', {'id': FILENAME_SPAN_ID})
		return [tag.text for tag in span_tags if tag.text not in EXCLUDED_FILES]
	except Exception as e:
		print(f"警告: 解析文件 {file_path} 时出错: {e}")
		return []


def process_directory(directory: str) -> None:
	"""处理目录中的所有HTML文件"""
	if not os.path.exists(directory):
		print(f"错误: 目录 {directory} 不存在")
		return
	if not os.path.isdir(directory):
		print(f"错误: {directory} 不是一个目录")
		return

	for root, dirs, files in os.walk(directory):
		for file in files:
			if file.endswith('.DS_Store'):
				continue
			file_path = os.path.join(root, file)
			real_path = os.path.realpath(file_path)
			real_dir = os.path.realpath(directory)
			if not real_path.startswith(real_dir):
				print(f"警告: 跳过目录外的文件: {file_path}")
				continue

			encoding = detect_file_encoding(file_path)
			if encoding is None:
				print(f"警告: 无法检测文件编码，跳过: {file_path}")
				continue

			filenames = extract_filenames_from_html(file_path, encoding)
			for filename in filenames:
				common.DataRecorder.check_exists(filename)


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始扫描 XFU HTML 页面...")
	process_directory(TARGET_DIRECTORY)
	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 扫描完成")


if __name__ == '__main__':
	main()
