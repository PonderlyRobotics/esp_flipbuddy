# BOARD_VARIANT=OTA  -> dual ota_0/ota_1 table (4 MB Super Mini)
list(APPEND SDKCONFIG_DEFAULTS boards/ESP32_GENERIC_S3/sdkconfig.ota)
