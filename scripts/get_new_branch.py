"""
遍历所有设备和分支，通过 Fastboot API 和 OTA API 检测未收录的 ROM。
合并自 HyperOS.fans getNewBranch.py + NuxtMR findNewBranches.py

全量探测约 20+ 万次请求，串行执行要三十多个小时，因此按「设备」划分任务后并发执行；
同一分支代号（device + branch code）内的请求仍串行，避免多个运营商同时写同一条 ROM。
"""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common

INCREMENT = ["1", "100", "200", "300"]
ONE_DEVICES = ['warm']
BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="

# 并发线程数：瓶颈是网络往返（单次约 0.5 秒），16 路已能压满带宽
MAX_WORKERS = 16
# 每完成这么多次探测打印一次进度
PROGRESS_EVERY = 200

_print_lock = threading.Lock()


def now() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log(message: str) -> None:
	"""线程安全的整行输出（并发下不用 \\r 覆盖，便于日志检索）"""
	with _print_lock:
		print(message, flush=True)


def get_device_info(device: str) -> dict | None:
	"""从数据库获取设备信息"""
	info = common.DatabaseManager.query_one(
		"SELECT code, devtag FROM devices WHERE device = %s LIMIT 1",
		params=(device,)
	)
	if not info:
		return None

	code = info[0] or device
	devtag = info[1] or device

	# Android 版本列表
	android_rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT android FROM roms WHERE device = %s AND android IS NOT NULL AND android != ''",
		params=(device,)
	)
	andvs = [row[0] for row in android_rows if row[0]]
	if not andvs:
		andvs = ['14.0']

	# OS 大版本列表
	os_rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT bigver FROM roms WHERE device = %s AND bigver IS NOT NULL AND bigver != ''",
		params=(device,)
	)
	oss = [row[0] for row in os_rows if row[0]]
	if not oss:
		oss = ['OS2.0']

	# 已知版本号集合
	ver_rows = common.DatabaseManager.query_all(
		"SELECT version FROM roms WHERE device = %s AND version IS NOT NULL",
		params=(device,)
	)
	known_versions = {row[0] for row in ver_rows if row[0]}

	return {
		'device': device,
		'code': code,
		'devtag': devtag,
		'android': andvs,
		'supports': oss,
		'known': known_versions,
	}


def get_known_branch_codes() -> set:
	"""获取数据库中已知的 device+code 组合"""
	known = set()
	rows = common.DatabaseManager.query_all(
		"SELECT device, code FROM devices WHERE code IS NOT NULL AND code != ''"
	)
	for row in rows:
		known.add((row[0], row[1]))
	return known


def build_device_jobs(device: str, known_codes: set) -> list[tuple]:
	"""生成一台设备需要探测的任务

	返回 [(分支代号, 描述, 类型, 参数)]，类型为 fastboot / ota。
	任务在同一线程池里并发执行，但相同分支代号的请求由调用方加锁串行。
	"""
	jobs: list[tuple] = []
	queried_fastboot_urls = set()
	queried_ota = set()
	devdata = get_device_info(device)
	if not devdata:
		return jobs

	code = devdata['code']
	devtag = devdata['devtag']

	for br in common.branches:
		devcode = device + br['code']

		# === 阶段1: Fastboot 查询 ===
		for carrier in br['carrier']:
			if device in ONE_DEVICES:
				url = BASE_URL + devcode + "&b=F&r=&n=" + carrier
			else:
				url = BASE_URL + devcode + "&b=F&r=" + br['region'] + "&n=" + carrier
			if url in queried_fastboot_urls:
				continue
			queried_fastboot_urls.add(url)
			jobs.append((devcode, url, 'fastboot', url))

		# === 阶段2: OTA 增量号探测（已知设备） ===
		if code:
			for os_ver in devdata['supports']:
				for andv in devdata['android']:
					for inc in INCREMENT:
						android_code = common.VersionUtils.android_code(andv)
						if br['tag'] == '':
							continue
						version = ver_replace(os_ver) + ".0." + inc + ".0." + android_code + devtag + br['tag']
						if version in devdata['known']:
							continue
						if (devcode, version) in queried_ota:
							continue
						queried_ota.add((devcode, version))
						region = '' if device in ONE_DEVICES else br['region']
						form = common.FirmwareParser.build_ota_form(device, devcode, region, 'F', br['zone'], andv, version)
						jobs.append((devcode, f"{devcode} {version}", 'ota', form))

		# === 阶段3: 未知 device+code 组合的 OTA 探测 ===
		elif (device, devcode) not in known_codes:
			if device not in ONE_DEVICES:
				if (devcode, '') in queried_ota:
					continue
				queried_ota.add((devcode, ''))
				form = common.FirmwareParser.build_ota_form(
					device, devcode, br['region'], 'F', br['zone'], '14.0', ''
				)
				jobs.append((devcode, devcode, 'ota', form))

	return jobs


def check_device(device: str, known_codes: set, progress: dict) -> tuple[str, int, float]:
	"""并发探测一台设备的所有任务，返回 (设备, 任务数, 耗时秒)"""
	started = time.time()
	jobs = build_device_jobs(device, known_codes)
	if not jobs:
		return device, 0, 0.0

	locks = {job[0]: threading.Lock() for job in jobs}

	def run(job):
		devcode, label, kind, payload = job
		with locks[devcode]:
			if kind == 'fastboot':
				common.NetworkClient.get_fastboot_info(payload)
			else:
				common.NetworkClient.fetch_and_check(payload)
			with _print_lock:
				progress['done'] += 1
				if progress['done'] % PROGRESS_EVERY == 0:
					print(f"{now()} 已完成 {progress['done']} 次探测（{label}）", flush=True)

	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
		for future in as_completed([pool.submit(run, job) for job in jobs]):
			future.result()

	return device, len(jobs), time.time() - started


def main() -> None:
	log(f"[{now()}] 开始新分支检测（并发 {MAX_WORKERS}）...")

	devices = list(dict.fromkeys(common.currentStable + common.unreleased))
	known_codes = get_known_branch_codes()
	progress = {'done': 0}

	for index, device in enumerate(devices, 1):
		name, count, elapsed = check_device(device, known_codes, progress)
		if count:
			log(f"{now()} [{index}/{len(devices)}] {name} 完成 {count} 次探测，"
					f"用时 {elapsed / 60:.1f} 分钟，累计 {progress['done']} 次")

	log(f"[{now()}] 新分支检测完成，共 {progress['done']} 次探测")


def ver_replace(os_ver):
	if "HyperOS" in os_ver:
		return os_ver.replace("HyperOS ", "OS")
	elif "MIUI" in os_ver:
		return os_ver.replace("MIUI ", "V")
	elif "STAN" in os_ver:
		return os_ver.replace("STAN ", "")
	else:
		return os_ver


if __name__ == '__main__':
	main()
