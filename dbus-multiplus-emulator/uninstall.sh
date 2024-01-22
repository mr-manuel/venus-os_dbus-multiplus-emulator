#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

sed -i "/$SERVICE_NAME/d" /data/rc.local
rm /service/$SERVICE_NAME
kill $(pgrep -f "supervise $SERVICE_NAME")

$SCRIPT_DIR/restart.sh

# remove settings
echo "Do you want to remove the dbus entries added by this driver? (y/N)"
read -r confirm
if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
    dbus -y com.victronenergy.settings /Settings RemoveSettings "%[ '/Alarm/System/GridLost', '/CanBms/SocketcanCan0/CustomName', '/CanBms/SocketcanCan0/ProductId', '/Canbus/can0/Profile', '/SystemSetup/AcInput1', '/SystemSetup/AcInput2' ]"
fi
