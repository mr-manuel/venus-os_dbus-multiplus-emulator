## dbus-mutliplus-emulator - Emulates a MultiPlus II 48/5000/70-50

<small>GitHub repository: [mr-manuel/venus-os_dbus-multiplus-emulator](https://github.com/mr-manuel/venus-os_dbus-multiplus-emulator)</small>

## Purpose
The script emulates a MultiPlus II in Venus OS. This allows to show the correct values in the overview.

## Supporting/Sponsoring this project

You like the project and you want to support me?

[<img src="https://github.md0.eu/uploads/donate-button.svg" height="50">](https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW)

## Config
There is nothing specific to configure and it should work out of the box. If you have multiple grid meters, batteries or phases, then a configuration is maybe needed. In this case edit the `dbus-multiplus-emulator.py` and search for the `USER CHANGABLE VALUES | START` section.

### Install

1. Login to your Venus OS device via SSH. See [Venus OS:Root Access](https://www.victronenergy.com/live/ccgx:root_access#root_access) for more details.

2. Execute this commands to download and extract the files:

    ```bash
    # change to temp folder
    cd /tmp

    # download driver
    wget -O /tmp/venus-os_dbus-multiplus-emulator.zip https://github.com/mr-manuel/venus-os_dbus-multiplus-emulator/archive/refs/heads/master.zip

    # If updating: cleanup old folder
    rm -rf /tmp/venus-os_dbus-multiplus-emulator-master

    # unzip folder
    unzip venus-os_dbus-multiplus-emulator.zip

    # If updating: cleanup existing driver
    rm -rf /data/etc/dbus-multiplus-emulator

    # copy files
    cp -R /tmp/venus-os_dbus-multiplus-emulator-master/dbus-multiplus-emulator/ /data/etc/
    ```

3. Run `bash /data/etc/dbus-multiplus-emulator/install.sh` to install the driver as service.

   The daemon-tools should start this service automatically within seconds.

### Uninstall

Run `/data/etc/dbus-multiplus-emulator/uninstall.sh`

### Restart

Run `/data/etc/dbus-multiplus-emulator/restart.sh`

### Debugging

The logs can be checked with `tail -n 100 -f /data/log/dbus-multiplus-emulator/current | tai64nlocal`
