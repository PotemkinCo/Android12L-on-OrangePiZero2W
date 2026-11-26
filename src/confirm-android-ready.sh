set -e
[ "$(getprop ro.build.version.sdk)" = 32 ]
[ "$(getprop sys.boot_completed)" = 1 ]
# Bluetooth HAL is unavailable in this minimal USB profile.
/system/bin/timeout 8 svc bluetooth disable >/dev/null 2>&1 || true
printf '__ANDROID_BOOT_COMPLETED__\n'
