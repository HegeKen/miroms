import common


# print(common.FirmwareParser.get_device_code("flare_global-ota_full-OS3.0.2.0.WHXMIXM-user-16.0-324cfe5a17.zip"))


new_arr = list(set(common.fullDevices))
print(sorted(new_arr))