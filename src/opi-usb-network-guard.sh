#!/system/bin/sh
set -e
# Development ADB is restricted to the USB host even when Wi-Fi is active.
for opi_port in 2323 5555; do
    /system/bin/iptables -w 3 -C INPUT ! -i usb0 -p tcp --dport "$opi_port" -j DROP 2>/dev/null || /system/bin/iptables -w 3 -I INPUT 1 ! -i usb0 -p tcp --dport "$opi_port" -j DROP
    /system/bin/ip6tables -w 3 -C INPUT -p tcp --dport "$opi_port" -j DROP 2>/dev/null || /system/bin/ip6tables -w 3 -I INPUT 1 -p tcp --dport "$opi_port" -j DROP
done
/system/bin/iptables -w 3 -C INPUT -p tcp --dport 5555 ! -s 192.168.246.1/32 -j DROP 2>/dev/null || /system/bin/iptables -w 3 -I INPUT 1 -p tcp --dport 5555 ! -s 192.168.246.1/32 -j DROP
