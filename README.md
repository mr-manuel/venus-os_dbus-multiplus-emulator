## dbus-mutliplus-emulator - Emulates a MultiPlus II 48/5000/70-50

<small>GitHub repository: [mr-manuel/venus-os_dbus-multiplus-emulator](https://github.com/mr-manuel/venus-os_dbus-multiplus-emulator)</small>

### Run

To run the script once:

1. Copy the `dbus-multiplus-emulator` folder to `/data/etc` on your Venus OS device

2. Run `python /data/etc/dbus-multiplus-emulator/multiplus-emulator.py` as root

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
