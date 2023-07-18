## dbus-mutliplus-emulator - Emulates a MultiPlus II 48/5000/70-50

<small>GitHub repository: [mr-manuel/venus-os_dbus-multiplus-emulator](https://github.com/mr-manuel/venus-os_dbus-multiplus-emulator)</small>

## Purpose
The script emulates a MultiPlus II in Venus OS. This allows to show the correct values in the overview.

## Config
There is nothing specific to configure and it should work out of the box. If you have multiple grid meters, batteries or phases, then a configuration is maybe needed. In this case edit the `dbus-multiplus-emulator.py` and search for the `USER CHANGABLE VALUES | START` section.

### Install

To run the script in the background:

1. Copy the `dbus-multiplus-emulator` folder to `/data/etc` on your Venus OS device

2. Run `bash /data/etc/dbus-multiplus-emulator/install.sh` as root

   The daemon-tools should start this service automatically within seconds.

### Uninstall

Run `/data/etc/dbus-multiplus-emulator/uninstall.sh`

### Restart

Run `/data/etc/dbus-multiplus-emulator/restart.sh`

### Debugging

The logs can be checked with `tail -n 100 -f /data/log/dbus-multiplus-emulator/current | tai64nlocal`


## Supporting/Sponsoring this project

You like the project and you want to support me?

[<img src="https://github.md0.eu/uploads/donate-button.svg" height="50">](https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW)
