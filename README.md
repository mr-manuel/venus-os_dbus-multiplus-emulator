## dbus-mutliplus-emulator - Emulates a MultiPlus II 48/5000/70-50

<small>GitHub repository: [mr-manuel/venus-os_dbus-multiplus-emulator](https://github.com/mr-manuel/venus-os_dbus-multiplus-emulator)</small>

## Index

1. [Disclaimer](#disclaimer)
1. [Supporting/Sponsoring this project](#supportingsponsoring-this-project)
1. [Purpose](#purpose)
1. [Config](#config)
1. [Install / Update](#install--update)
1. [Uninstall](#uninstall)
1. [Restart](#restart)
1. [Debugging](#debugging)
1. [Compatibility](#compatibility)


## Disclaimer

I wrote this script for myself. I'm not responsible, if you damage something using my script.

## Supporting/Sponsoring this project

You like the project and you want to support me?

[<img src="https://github.md0.eu/uploads/donate-button.svg" height="50">](https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW)


## Purpose
The script emulates a MultiPlus II in Venus OS. This allows to show the correct values in the overview.

## Config
There is nothing specific to configure and it should work out of the box for systems that have only `L1`. If you have multiple phases, grid meters and/or batteries, then a configuration is maybe needed. In this case edit the `dbus-multiplus-emulator.py` and search for the `USER CHANGABLE VALUES | START` section.

In a multi-phase system, the DC loads are distributed based on the combined power from each phase of the grid and PV inverters. To achieve more accurate readings, you need to provide the power going in and out of the charger/inverter on the AC side. You can then use the [`dbus-mqtt-grid`](https://github.com/mr-manuel/venus-os_dbus-mqtt-grid) driver and configure it as an AC load to input these values into the emulator.

⚠️ Please note that the `AC Loads` value may not exactly match the actual values, because losses are included as part of the load.


## Install / Update

1. Login to your Venus OS device via SSH. See [Venus OS:Root Access](https://www.victronenergy.com/live/ccgx:root_access#root_access) for more details.

2. Execute this commands to download and copy the files:

    ```bash
    wget -O /tmp/download_dbus-multiplus-emulator.sh https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-multiplus-emulator/master/download.sh

    bash /tmp/download_dbus-multiplus-emulator.sh
    ```

3. Select the version you want to install.

### Extra steps for your first installation

4. Edit the config file if you have a multi-phase system or if you want to have a custom configuration:

    ```bash
    nano /data/etc/dbus-multiplus-emulator-2/config.ini
    ```

    Otherwise, skip this step.

5. Install the driver as a service:

    ```bash
    bash /data/etc/dbus-multiplus-emulator/install.sh
    ```

    The daemon-tools should start this service automatically within seconds.

## Uninstall

Run `/data/etc/dbus-multiplus-emulator/uninstall.sh`

## Restart

Run `/data/etc/dbus-multiplus-emulator/restart.sh`

## Debugging

The service status can be checked with svstat `svstat /service/dbus-multiplus-emulator`

This will output somethink like `/service/dbus-multiplus-emulator: up (pid 5845) 185 seconds`

If the seconds are under 5 then the service crashes and gets restarted all the time. If you do not see anything in the logs you can increase the log level in `/data/etc/dbus-multiplus-emulator/dbus-multiplus-emulator.py` by changing `level=logging.WARNING` to `level=logging.INFO` or `level=logging.DEBUG`

If the script stops with the message `dbus.exceptions.NameExistsException: Bus name already exists: com.victronenergy.grid.mqtt_grid"` it means that the service is still running or another service is using that bus name.

## Compatibility

This software supports the latest three stable versions of Venus OS. It may also work on older versions, but this is not guaranteed.
