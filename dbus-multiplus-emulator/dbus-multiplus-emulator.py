#!/usr/bin/env python

from gi.repository import GLib
import platform
import logging
import sys
import os
import _thread
from time import time
from typing import Union
import json


# import Victron Energy packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))
from vedbus import VeDbusService
from dbusmonitor import DbusMonitor

# use WARNING for default, INFO for displaying actual steps and values, DEBUG for debugging
logging.basicConfig(level=logging.WARNING)


# ------------------ USER CHANGABLE VALUES | START ------------------

# enter grid frequency
grid_frequency = 50.0000

# enter grid nominal voltage
# Europe
grid_nominal_voltage = 230.0
# UK/USA
# grid_nominal_voltage = 120.0

# enter the dbusServiceName from which the battery data should be fetched, if there is more than one
# e.g. com.victronenergy.battery.mqtt_battery_41
dbusServiceNameBattery = ""

# enter the dbusServiceName from which the grid meter data should be fetched, if there is more than one
# e.g. com.victronenergy.grid.mqtt_grid_31
dbusServiceNameGrid = ""

# enter the maximum power of the inverter of a single phase
inverter_max_power = 4500

# uncomment or change the phase combination you are using
# default: ["L1"]
phase_used = ["L1"]
# phase_used = ["L1", "L2"]
# phase_used = ["L1", "L2", "L3"]

# ------------------ USER CHANGABLE VALUES | END --------------------


# specify how many phases are connected
phase_count = len(phase_used)
# create dictionary for later to count watt hours
data_watt_hours = {"time_creation": int(time()), "count": 0}
# calculate and save watthours after every x seconds
data_watt_hours_timespan = 60
# save file to non volatile storage after x seconds
data_watt_hours_save = 900
# file to save watt hours on persistent storage
data_watt_hours_storage_file = "/data/etc/dbus-multiplus-emulator/data_watt_hours.json"
# file to save many writing operations (best on ramdisk to not wear SD card)
data_watt_hours_working_file = (
    "/var/volatile/tmp/dbus-multiplus-emulator_data_watt_hours.json"
)
# get last modification timestamp
timestamp_storage_file = (
    os.path.getmtime(data_watt_hours_storage_file)
    if os.path.isfile(data_watt_hours_storage_file)
    else 0
)

# load data to prevent sending 0 watthours for OutToInverter (charging)/InverterToOut (discharging) before the first loop
# check if file in volatile storage exists
if os.path.isfile(data_watt_hours_working_file):
    with open(data_watt_hours_working_file, "r") as file:
        file = open(data_watt_hours_working_file, "r")
        json_data = json.load(file)
        logging.info(
            "Loaded JSON for OutToInverter (charging)/InverterToOut (discharging) once"
        )
        logging.debug(json.dumps(json_data))
# if not, check if file in persistent storage exists
elif os.path.isfile(data_watt_hours_storage_file):
    with open(data_watt_hours_storage_file, "r") as file:
        file = open(data_watt_hours_storage_file, "r")
        json_data = json.load(file)
        logging.info(
            "Loaded JSON for OutToInverter (charging)/InverterToOut (discharging) once from persistent storage"
        )
        logging.debug(json.dumps(json_data))
else:
    json_data = {}


class DbusMultiPlusEmulator:
    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        productname="MultiPlus-II xx/5000/xx-xx (emulated)",
        connection="VE.Bus",
    ):
        self._dbusservice = VeDbusService(servicename)
        self._paths = paths

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)  # ok
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unkown version, and running on Python " + platform.python_version(),
        )  # ok
        self._dbusservice.add_path("/Mgmt/Connection", connection)  # ok

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)  # ok
        self._dbusservice.add_path("/ProductId", 2623)  # ok
        self._dbusservice.add_path("/ProductName", productname)  # ok
        self._dbusservice.add_path("/CustomName", "")  # ok
        self._dbusservice.add_path("/FirmwareVersion", 1296)  # ok
        self._dbusservice.add_path("/HardwareVersion", "0.1.0 (20240602)")
        self._dbusservice.add_path("/Connected", 1)  # ok

        # self._dbusservice.add_path('/Latency', None)
        # self._dbusservice.add_path('/ErrorCode', 0)
        # self._dbusservice.add_path('/Position', 0)
        # self._dbusservice.add_path('/StatusCode', 0)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )

        # ### read values from battery
        # Why this dummy? Because DbusMonitor expects these values to be there, even though we don't
        # need them. So just add some dummy data. This can go away when DbusMonitor is more generic.
        dummy = {"code": None, "whenToLog": "configChange", "accessLevel": None}
        dbus_tree = {}

        dbus_tree.update(
            {
                "com.victronenergy.battery": {
                    # "/Connected": dummy,
                    # "/ProductName": dummy,
                    # "/Mgmt/Connection": dummy,
                    # "/DeviceInstance": dummy,
                    "/Dc/0/Current": dummy,
                    "/Dc/0/Power": dummy,
                    "/Dc/0/Temperature": dummy,
                    "/Dc/0/Voltage": dummy,
                    "/Soc": dummy,
                    # '/Sense/Current': dummy,
                    # '/TimeToGo': dummy,
                    # '/ConsumedAmphours': dummy,
                    # '/ProductId': dummy,
                    # '/CustomName': dummy,
                    "/Info/ChargeMode": dummy,
                    "/Info/BatteryLowVoltage": dummy,
                    "/Info/MaxChargeCurrent": dummy,
                    "/Info/MaxChargeVoltage": dummy,
                    "/Info/MaxDischargeCurrent": dummy,
                }
            }
        )
        # create empty dictionary will be updated later
        self.batteryValues = {
            "/Dc/0/Current": None,
            "/Dc/0/Power": None,
            "/Dc/0/Temperature": None,
            "/Dc/0/Voltage": None,
            "/Soc": None,
            "/Info/ChargeMode": "",
            "/Info/BatteryLowVoltage": None,
            "/Info/MaxChargeCurrent": None,
            "/Info/MaxChargeVoltage": None,
            "/Info/MaxDischargeCurrent": None,
        }

        dbus_tree.update(
            {
                "com.victronenergy.grid": {
                    # '/Connected': dummy,
                    # '/ProductName': dummy,
                    # '/Mgmt/Connection': dummy,
                    # '/ProductId' : dummy,
                    # '/DeviceType' : dummy,
                    "/Ac/L1/Power": dummy,
                    "/Ac/L2/Power": dummy,
                    "/Ac/L3/Power": dummy,
                    "/Ac/L1/Current": dummy,
                    "/Ac/L2/Current": dummy,
                    "/Ac/L3/Current": dummy,
                    "/Ac/L1/Voltage": dummy,
                    "/Ac/L2/Voltage": dummy,
                    "/Ac/L3/Voltage": dummy,
                    "/Ac/L1/Frequency": dummy,
                    "/Ac/L2/Frequency": dummy,
                    "/Ac/L3/Frequency": dummy,
                    # ---
                    "/Ac/Power": dummy,
                    "/Ac/Current": dummy,
                    "/Ac/Voltage": dummy,
                }
            }
        )
        # create empty dictionary will be updated later
        self.gridValues = {
            "/Ac/L1/Power": None,
            "/Ac/L2/Power": None,
            "/Ac/L3/Power": None,
            "/Ac/L1/Current": None,
            "/Ac/L2/Current": None,
            "/Ac/L3/Current": None,
            "/Ac/L1/Voltage": None,
            "/Ac/L2/Voltage": None,
            "/Ac/L3/Voltage": None,
            "/Ac/L1/Frequency": None,
            "/Ac/L2/Frequency": None,
            "/Ac/L3/Frequency": None,
            # ---
            "/Ac/Power": None,
            "/Ac/Current": None,
            "/Ac/Voltage": None,
        }

        """
        dbus_tree.update({
            "com.victronenergy.system": {
                "/Dc/Battery/BatteryService": dummy,
                "/Dc/Battery/ConsumedAmphours": dummy,
                "/Dc/Battery/Current": dummy,
                "/Dc/Battery/Power": dummy,
                "/Dc/Battery/ProductId": dummy,
                "/Dc/Battery/Soc": dummy,
                "/Dc/Battery/State": dummy,
                "/Dc/Battery/Temperature": dummy,
                "/Dc/Battery/TemperatureService": dummy,
                "/Dc/Battery/TimeToGo": dummy,
                "/Dc/Battery/Voltage": dummy,
                "/Dc/Battery/VoltageService": dummy,
            },
        })
        """

        # self._dbusreadservice = DbusMonitor('com.victronenergy.battery.zero')
        self._dbusmonitor = self._create_dbus_monitor(
            dbus_tree,
            valueChangedCallback=self._dbus_value_changed,
            deviceAddedCallback=self._device_added,
            deviceRemovedCallback=self._device_removed,
        )

        GLib.timeout_add(1000, self._update)  # pause 1000ms before the next request

    def _create_dbus_monitor(self, *args, **kwargs):
        return DbusMonitor(*args, **kwargs)

    def _dbus_value_changed(
        self, dbusServiceName, dbusPath, dict, changes, deviceInstance
    ):
        self._changed = True

        if (
            dbusServiceNameBattery == ""
            and dbusServiceName.startswith("com.victronenergy.battery")
        ) or (
            dbusServiceNameBattery != "" and dbusServiceName == dbusServiceNameBattery
        ):
            self.batteryValues.update({str(dbusPath): changes["Value"]})

        if (
            dbusServiceNameGrid == ""
            and dbusServiceName.startswith("com.victronenergy.grid")
        ) or (dbusServiceNameGrid != "" and dbusServiceName == dbusServiceNameGrid):
            self.gridValues.update({str(dbusPath): changes["Value"]})

        # print('_dbus_value_changed')
        # print(dbusServiceName)
        # print(dbusPath)
        # print(dict)
        # print(changes)
        # print(deviceInstance)

        # print(self.batteryValues)
        # print(self.gridValues)

    def _device_added(self, service, instance, do_service_change=True):
        # print('_device_added')
        # print(service)
        # print(instance)
        # print(do_service_change)

        pass

    def _device_removed(self, service, instance):
        # print('_device_added')
        # print(service)
        # print(instance)

        pass

    def zeroIfNone(self, value: Union[int, float, None]) -> float:
        """
        Returns the value if it is not None, otherwise 0.
        """
        return value if value is not None else 0

    def _update(self):
        global data_watt_hours, data_watt_hours_timespan, data_watt_hours_save, data_watt_hours_storage_file, data_watt_hours_working_file, json_data, timestamp_storage_file

        # ##################################################################################################################

        # # # calculate watthours
        # measure power and calculate watthours, since it provides only watthours for production/import/consumption and no export
        # divide charging and discharging from dc
        dc_power = self.zeroIfNone(self.batteryValues["/Dc/0/Power"])
        # charging (+)
        dc_power_charging = dc_power if dc_power > 0 else 0
        # discharging (-)
        dc_power_discharging = dc_power * -1 if dc_power < 0 else 0

        # timestamp
        timestamp = int(time())

        # check if x seconds are passed, if not sum values for calculation
        if data_watt_hours["time_creation"] + data_watt_hours_timespan > timestamp:
            data_watt_hours_dc = {
                "charging": round(
                    (
                        data_watt_hours["dc"]["charging"] + dc_power_charging
                        if "dc" in data_watt_hours
                        else dc_power_charging
                    ),
                    3,
                ),
                "discharging": round(
                    (
                        data_watt_hours["dc"]["discharging"] + dc_power_discharging
                        if "dc" in data_watt_hours
                        else dc_power_discharging
                    ),
                    3,
                ),
            }

            data_watt_hours.update(
                {
                    "dc": data_watt_hours_dc,
                    "count": data_watt_hours["count"] + 1,
                }
            )

            logging.info("--> data_watt_hours(): %s" % json.dumps(data_watt_hours))

        # build mean, calculate time diff and Wh and write to file
        else:
            # check if file in volatile storage exists
            if os.path.isfile(data_watt_hours_working_file):
                with open(data_watt_hours_working_file, "r") as file:
                    file = open(data_watt_hours_working_file, "r")
                    data_watt_hours_old = json.load(file)
                    logging.info("Loaded JSON")
                    logging.info(json.dumps(data_watt_hours_old))

            # if not, check if file in persistent storage exists
            elif os.path.isfile(data_watt_hours_storage_file):
                with open(data_watt_hours_storage_file, "r") as file:
                    file = open(data_watt_hours_storage_file, "r")
                    data_watt_hours_old = json.load(file)
                    logging.info("Loaded JSON from persistent storage")
                    logging.info(json.dumps(data_watt_hours_old))

            # if not, generate data
            else:
                data_watt_hours_old_dc = {
                    "charging": 0,
                    "discharging": 0,
                }
                data_watt_hours_old = {"dc": data_watt_hours_old_dc}
                logging.info("Generated JSON")
                logging.info(json.dumps(data_watt_hours_old))

            # factor to calculate Watthours: mean power * measuuring period / 3600 seconds (1 hour)
            factor = (timestamp - data_watt_hours["time_creation"]) / 3600

            dc_charging = round(
                data_watt_hours_old["dc"]["charging"]
                + (
                    data_watt_hours["dc"]["charging"]
                    / data_watt_hours["count"]
                    * factor
                )
                / 1000,
                3,
            )
            dc_discharging = round(
                data_watt_hours_old["dc"]["discharging"]
                + (
                    data_watt_hours["dc"]["discharging"]
                    / data_watt_hours["count"]
                    * factor
                )
                / 1000,
                3,
            )

            # update previously set data
            json_data = {
                "dc": {
                    "charging": dc_charging,
                    "discharging": dc_discharging,
                }
            }

            # save data to volatile storage
            with open(data_watt_hours_working_file, "w") as file:
                file.write(json.dumps(json_data))

            # save data to persistent storage if time is passed
            if timestamp_storage_file + data_watt_hours_save < timestamp:
                with open(data_watt_hours_storage_file, "w") as file:
                    file.write(json.dumps(json_data))
                timestamp_storage_file = timestamp
                logging.info(
                    "Written JSON for OutToInverter (charging)/InverterToOut (discharging) to persistent storage."
                )

            # begin a new cycle
            data_watt_hours_dc = {
                "charging": round(dc_power_charging, 3),
                "discharging": round(dc_power_discharging, 3),
            }

            data_watt_hours = {
                "time_creation": timestamp,
                "dc": data_watt_hours_dc,
                "count": 1,
            }

            logging.info("--> data_watt_hours(): %s" % json.dumps(data_watt_hours))

        # update values in dbus

        # get values from BMS
        # for bubble flow in chart and load visualization
        # L1 ----
        self._dbusservice["/Ac/ActiveIn/L1/F"] = (
            self.gridValues["/Ac/L1/Frequency"]
            if self.gridValues["/Ac/L1/Frequency"] is not None and "L1" in phase_used
            else (
                grid_frequency
                if self.gridValues["/Ac/L1/Frequency"] is None and "L1" in phase_used
                else None
            )
        )
        self._dbusservice["/Ac/ActiveIn/L1/I"] = (
            self.gridValues["/Ac/L1/Current"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/P"] = (
            self.gridValues["/Ac/L1/Power"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/S"] = (
            self.gridValues["/Ac/L1/Power"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/V"] = (
            self.gridValues["/Ac/L1/Voltage"] if "L1" in phase_used else None
        )

        # L2 ----
        self._dbusservice["/Ac/ActiveIn/L2/F"] = (
            self.gridValues["/Ac/L2/Frequency"]
            if self.gridValues["/Ac/L2/Frequency"] is not None and "L2" in phase_used
            else (
                grid_frequency
                if self.gridValues["/Ac/L2/Frequency"] is None and "L2" in phase_used
                else None
            )
        )
        self._dbusservice["/Ac/ActiveIn/L2/I"] = (
            self.gridValues["/Ac/L2/Current"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/P"] = (
            self.gridValues["/Ac/L2/Power"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/S"] = (
            self.gridValues["/Ac/L2/Power"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/V"] = (
            self.gridValues["/Ac/L2/Voltage"] if "L2" in phase_used else None
        )

        # L3 ----
        self._dbusservice["/Ac/ActiveIn/L3/F"] = (
            self.gridValues["/Ac/L3/Frequency"]
            if self.gridValues["/Ac/L3/Frequency"] is not None and "L3" in phase_used
            else (
                grid_frequency
                if self.gridValues["/Ac/L3/Frequency"] is None and "L3" in phase_used
                else None
            )
        )
        self._dbusservice["/Ac/ActiveIn/L3/I"] = (
            self.gridValues["/Ac/L3/Current"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/P"] = (
            self.gridValues["/Ac/L3/Power"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/S"] = (
            self.gridValues["/Ac/L3/Power"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/V"] = (
            self.gridValues["/Ac/L3/Voltage"] if "L3" in phase_used else None
        )

        # calculate total values
        self._dbusservice["/Ac/ActiveIn/P"] = (
            self.zeroIfNone(self.gridValues["/Ac/L1/Power"])
            + self.zeroIfNone(self.gridValues["/Ac/L2/Power"])
            + self.zeroIfNone(self.gridValues["/Ac/L3/Power"])
        )
        self._dbusservice["/Ac/ActiveIn/S"] = self._dbusservice["/Ac/ActiveIn/P"]

        # get values from BMS
        # for bubble flow in chart and load visualization
        self._dbusservice["/Ac/NumberOfPhases"] = phase_count

        # L1 ----
        self._dbusservice["/Ac/Out/L1/F"] = (
            self._dbusservice["/Ac/ActiveIn/L1/F"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L1/P"] = (
            round(
                (
                    self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L1/P"])
                    + (
                        self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) / phase_count
                        if self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) != 0
                        else 0
                    )
                )
                * -1,
                0,
            )
            if "L1" in phase_used
            else None
        )
        self._dbusservice["/Ac/Out/L1/S"] = (
            self._dbusservice["/Ac/Out/L1/P"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L1/NominalInverterPower"] = (
            inverter_max_power if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L1/V"] = (
            self._dbusservice["/Ac/ActiveIn/L1/V"] if "L1" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L1/I"] = (
            (
                round(
                    self._dbusservice["/Ac/Out/L1/P"]
                    / self._dbusservice["/Ac/Out/L1/V"],
                    2,
                )
                if self._dbusservice["/Ac/Out/L1/V"] is not None
                and self._dbusservice["/Ac/Out/L1/V"] != 0
                else 0
            )
            if "L1" in phase_used
            else None
        )

        # L2 ----
        self._dbusservice["/Ac/Out/L2/F"] = (
            self._dbusservice["/Ac/ActiveIn/L2/F"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L2/P"] = (
            round(
                (
                    self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L2/P"])
                    + (
                        self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) / phase_count
                        if self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) != 0
                        else 0
                    )
                )
                * -1,
                0,
            )
            if "L2" in phase_used
            else None
        )
        self._dbusservice["/Ac/Out/L2/S"] = (
            self._dbusservice["/Ac/Out/L2/P"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L2/NominalInverterPower"] = (
            inverter_max_power if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L2/V"] = (
            self._dbusservice["/Ac/ActiveIn/L2/V"] if "L2" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L2/I"] = (
            (
                round(
                    self._dbusservice["/Ac/Out/L2/P"]
                    / self._dbusservice["/Ac/Out/L2/V"],
                    2,
                )
                if self._dbusservice["/Ac/Out/L2/V"] is not None
                and self._dbusservice["/Ac/Out/L2/V"] != 0
                else 0
            )
            if "L2" in phase_used
            else None
        )

        # L3 ----
        self._dbusservice["/Ac/Out/L3/F"] = (
            self._dbusservice["/Ac/ActiveIn/L3/F"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L3/P"] = (
            round(
                (
                    self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L3/P"])
                    + (
                        self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) / phase_count
                        if self.zeroIfNone(self.batteryValues["/Dc/0/Power"]) != 0
                        else 0
                    )
                )
                * -1,
                0,
            )
            if "L3" in phase_used
            else None
        )
        self._dbusservice["/Ac/Out/L3/S"] = (
            self._dbusservice["/Ac/Out/L3/P"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L3/NominalInverterPower"] = (
            inverter_max_power if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L3/V"] = (
            self._dbusservice["/Ac/ActiveIn/L3/V"] if "L3" in phase_used else None
        )
        self._dbusservice["/Ac/Out/L3/I"] = (
            (
                round(
                    self._dbusservice["/Ac/Out/L3/P"]
                    / self._dbusservice["/Ac/Out/L3/V"],
                    2,
                )
                if self._dbusservice["/Ac/Out/L3/V"] is not None
                and self._dbusservice["/Ac/Out/L3/V"] != 0
                else 0
            )
            if "L3" in phase_used
            else None
        )

        # calculate total values
        self._dbusservice["/Ac/Out/NominalInverterPower"] = (
            self.zeroIfNone(self._dbusservice["/Ac/Out/L1/NominalInverterPower"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L2/NominalInverterPower"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L3/NominalInverterPower"])
        )
        self._dbusservice["/Ac/Out/P"] = (
            self.zeroIfNone(self._dbusservice["/Ac/Out/L1/P"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L2/P"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L3/P"])
        )
        self._dbusservice["/Ac/Out/S"] = (
            self.zeroIfNone(self._dbusservice["/Ac/Out/L1/S"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L2/S"])
            + self.zeroIfNone(self._dbusservice["/Ac/Out/L3/S"])
        )

        self._dbusservice["/BatteryOperationalLimits/BatteryLowVoltage"] = (
            self.batteryValues["/Info/BatteryLowVoltage"]
        )
        self._dbusservice["/BatteryOperationalLimits/MaxChargeCurrent"] = (
            self.batteryValues["/Info/MaxChargeCurrent"]
        )
        self._dbusservice["/BatteryOperationalLimits/MaxChargeVoltage"] = (
            self.batteryValues["/Info/MaxChargeVoltage"]
        )
        self._dbusservice["/BatteryOperationalLimits/MaxDischargeCurrent"] = (
            self.batteryValues["/Info/MaxDischargeCurrent"]
        )
        self._dbusservice["/BatterySense/Temperature"] = self.batteryValues[
            "/Dc/0/Temperature"
        ]

        # get values from BMS
        # for bubble flow in GUI
        self._dbusservice["/Dc/0/Current"] = self.batteryValues["/Dc/0/Current"]
        self._dbusservice["/Dc/0/MaxChargeCurrent"] = self.batteryValues[
            "/Info/MaxChargeCurrent"
        ]
        self._dbusservice["/Dc/0/Power"] = self.batteryValues["/Dc/0/Power"]
        self._dbusservice["/Dc/0/Temperature"] = self.batteryValues["/Dc/0/Temperature"]
        self._dbusservice["/Dc/0/Voltage"] = (
            self.batteryValues["/Dc/0/Voltage"]
            if self.batteryValues["/Dc/0/Voltage"] is not None
            else (
                round(
                    self.batteryValues["/Dc/0/Power"]
                    / self.batteryValues["/Dc/0/Current"],
                    2,
                )
                if self.batteryValues["/Dc/0/Power"] is not None
                and self.batteryValues["/Dc/0/Current"] is not None
                else None
            )
        )

        self._dbusservice["/Devices/0/UpTime"] = int(time()) - time_driver_started

        if phase_count >= 2:
            self._dbusservice["/Devices/1/UpTime"] = int(time()) - time_driver_started

        if phase_count == 3:
            self._dbusservice["/Devices/2/UpTime"] = int(time()) - time_driver_started

        self._dbusservice["/Energy/InverterToAcOut"] = (
            json_data["dc"]["discharging"]
            if "dc" in json_data and "discharging" in json_data["dc"]
            else 0
        )
        self._dbusservice["/Energy/OutToInverter"] = (
            json_data["dc"]["charging"]
            if "dc" in json_data and "charging" in json_data["dc"]
            else 0
        )

        self._dbusservice["/Hub/ChargeVoltage"] = self.batteryValues[
            "/Info/MaxChargeVoltage"
        ]

        self._dbusservice["/Leds/Absorption"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Absorption") else 0
        )
        self._dbusservice["/Leds/Bulk"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Bulk") else 0
        )
        self._dbusservice["/Leds/Float"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Float") else 0
        )
        self._dbusservice["/Soc"] = self.batteryValues["/Soc"]

        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index

        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change


def create_device_dbus_paths(device_number: int = 0):
    """
    Create the dbus paths for the device.
    """

    global _w, _n, _v

    paths_dbus = {
        f"/Devices/{device_number}/Ac/In/L2/P": {"initial": None, "textformat": _w},
        f"/Devices/{device_number}/Ac/In/P": {"initial": None, "textformat": _w},
        f"/Devices/{device_number}/Ac/Inverter/P": {"initial": None, "textformat": _w},
        f"/Devices/{device_number}/Ac/Out/L2/P": {"initial": None, "textformat": _w},
        f"/Devices/{device_number}/Ac/Out/P": {"initial": None, "textformat": _w},
        f"/Devices/{device_number}/Assistants": {
            "initial": [
                139,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ],
            "textformat": None,
        },
        f"/Devices/{device_number}/CNBFirmwareVersion": {
            "initial": 2204156,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Diagnostics/UBatRipple": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Diagnostics/UBatTerminal": {
            "initial": None,
            "textformat": _v,
        },
        f"/Devices/{device_number}/Diagnostics/UBatVSense": {
            "initial": None,
            "textformat": _v,
        },
        f"/Devices/{device_number}/ErrorAndWarningFlags/NSErrConnectFrustratedByRelayTest": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ErrorAndWarningFlags/NSErrRelayTestKeepsFailing": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ErrorAndWarningFlags/RawFlags": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ErrorAndWarningFlags/WarnRelayTestRecentlyFailed": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/AcIn1Available": {
            "initial": 1,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/BolTimeoutOccured": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/ChargeDisabledDueToLowTemp": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/ChargeIsDisabled": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/DMCGeneratorSelected": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/GridRelayReport/Code": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/GridRelayReport/Count": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/GridRelayReport/Reset": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/HighDcCurrent": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/HighDcVoltage": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/IgnoreAcIn1": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/IgnoreAcIn1AssistantsVs": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/MainsPllLocked": {
            "initial": 1,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/NPFGeneratorSelected": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/PcvPotmeterOnZero": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/PowerPackPreOverload": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/PreferRenewableEnergy": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/PreferRenewableEnergyActive": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/RawFlags0": {
            "initial": 268697648,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/RawFlags1": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/RelayTestOk": {
            "initial": 1,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/SocTooLowToInvert": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/SustainMode": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/SwitchoverInfo/Connecting": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/SwitchoverInfo/Delay": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/SwitchoverInfo/ErrorFlags": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/TemperatureHighForceBypass": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/VeBusNetworkQualityCounter": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/ExtendStatus/WaitingForRelayTest": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/FirmwareSubVersion": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/FirmwareVersion": {
            "initial": 1296,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Info/DeltaTBatNominalTBatMinimum": {
            "initial": 45,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Info/MaximumRelayCurrentAC1": {
            "initial": 50,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Info/MaximumRelayCurrentAC2": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/0/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/0/Time": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/1/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/1/Time": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/2/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/2/Time": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/3/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/3/Time": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/4/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/InterfaceProtectionLog/4/Time": {
            "initial": None,
            "textformat": _n,
        },
        # ----
        f"/Devices/{device_number}/ProductId": {
            "initial": 9763,
            "textformat": _n,
        },
        f"/Devices/{device_number}/SerialNumber": {
            "initial": "HQ00000AA0" + str(device_number + 1),
            "textformat": _s,
        },
        f"/Devices/{device_number}/Settings/AssistCurrentBoostFactor": {
            "initial": 2.0,
            "textformat": _n1,
        },
        f"/Devices/{device_number}/Settings/InverterOutputVoltage": {
            "initial": 230.0,
            "textformat": _n1,
        },
        f"/Devices/{device_number}/Settings/PowerAssistEnabled": {
            "initial": False,
            "textformat": None,
        },
        f"/Devices/{device_number}/Settings/ReadProgress": {
            "initial": 100,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Settings/ResetRequired": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Settings/UpsFunction": {
            "initial": False,
            "textformat": None,
        },
        f"/Devices/{device_number}/Settings/WriteProgress": {
            "initial": None,
            "textformat": _n,
        },
        f"/Devices/{device_number}/UpTime": {
            "initial": 0,
            "textformat": _n,
        },
        f"/Devices/{device_number}/Version": {"initial": 2987520, "textformat": _s},
    }

    return paths_dbus


# formatting
def _wh(p, v):
    return str("%.2f" % v) + "Wh"


def _a(p, v):
    return str("%.2f" % v) + "A"


def _w(p, v):
    return str("%i" % v) + "W"


def _va(p, v):
    return str("%i" % v) + "VA"


def _v(p, v):
    return str("%i" % v) + "V"


def _hz(p, v):
    return str("%.4f" % v) + "Hz"


def _c(p, v):
    return str("%i" % v) + "°C"


def _percent(p, v):
    return str("%.1f" % v) + "%"


def _n(p, v):
    return str("%i" % v)


def _n1(p, v):
    return str("%.1f" % v)


def _s(p, v):
    return str("%s" % v)


def main():
    global time_driver_started

    _thread.daemon = True  # allow the program to quit

    from dbus.mainloop.glib import DBusGMainLoop

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    paths_multiplus_dbus = {
        "/Ac/ActiveIn/ActiveInput": {"initial": 0, "textformat": _n},
        "/Ac/ActiveIn/Connected": {"initial": 1, "textformat": _n},
        "/Ac/ActiveIn/CurrentLimit": {"initial": 50.0, "textformat": _a},
        "/Ac/ActiveIn/CurrentLimitIsAdjustable": {"initial": 1, "textformat": _n},
        # ----
        "/Ac/ActiveIn/L1/F": {"initial": None, "textformat": _hz},
        "/Ac/ActiveIn/L1/I": {"initial": None, "textformat": _a},
        "/Ac/ActiveIn/L1/P": {"initial": None, "textformat": _w},
        "/Ac/ActiveIn/L1/S": {"initial": None, "textformat": _va},
        "/Ac/ActiveIn/L1/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/ActiveIn/L2/F": {"initial": None, "textformat": _hz},
        "/Ac/ActiveIn/L2/I": {"initial": None, "textformat": _a},
        "/Ac/ActiveIn/L2/P": {"initial": None, "textformat": _w},
        "/Ac/ActiveIn/L2/S": {"initial": None, "textformat": _va},
        "/Ac/ActiveIn/L2/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/ActiveIn/L3/F": {"initial": None, "textformat": _hz},
        "/Ac/ActiveIn/L3/I": {"initial": None, "textformat": _a},
        "/Ac/ActiveIn/L3/P": {"initial": None, "textformat": _w},
        "/Ac/ActiveIn/L3/S": {"initial": None, "textformat": _va},
        "/Ac/ActiveIn/L3/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/ActiveIn/P": {"initial": 0, "textformat": _w},
        "/Ac/ActiveIn/S": {"initial": 0, "textformat": _va},
        # ----
        "/Ac/Control/IgnoreAcIn1": {"initial": 0, "textformat": _n},
        "/Ac/Control/RemoteGeneratorSelected": {"initial": 0, "textformat": _n},
        # ----
        "/Ac/In/1/CurrentLimit": {"initial": 50.0, "textformat": _a},
        "/Ac/In/1/CurrentLimitIsAdjustable": {"initial": 1, "textformat": _n},
        # ----
        "/Ac/In/2/CurrentLimit": {"initial": None, "textformat": _a},
        "/Ac/In/2/CurrentLimitIsAdjustable": {"initial": None, "textformat": _n},
        # ----
        "/Ac/NumberOfAcInputs": {"initial": 1, "textformat": _n},
        "/Ac/NumberOfPhases": {"initial": phase_count, "textformat": _n},
        # ----
        "/Ac/Out/L1/F": {"initial": None, "textformat": _hz},
        "/Ac/Out/L1/I": {"initial": None, "textformat": _a},
        "/Ac/Out/L1/NominalInverterPower": {"initial": None, "textformat": _w},
        "/Ac/Out/L1/P": {"initial": None, "textformat": _w},
        "/Ac/Out/L1/S": {"initial": None, "textformat": _va},
        "/Ac/Out/L1/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/Out/L2/F": {"initial": None, "textformat": _hz},
        "/Ac/Out/L2/I": {"initial": None, "textformat": _a},
        "/Ac/Out/L2/NominalInverterPower": {"initial": None, "textformat": _w},
        "/Ac/Out/L2/P": {"initial": None, "textformat": _w},
        "/Ac/Out/L2/S": {"initial": None, "textformat": _va},
        "/Ac/Out/L2/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/Out/L3/F": {"initial": None, "textformat": _hz},
        "/Ac/Out/L3/I": {"initial": None, "textformat": _a},
        "/Ac/Out/L3/NominalInverterPower": {"initial": None, "textformat": _w},
        "/Ac/Out/L3/P": {"initial": None, "textformat": _w},
        "/Ac/Out/L3/S": {"initial": None, "textformat": _va},
        "/Ac/Out/L3/V": {"initial": None, "textformat": _v},
        # ----
        "/Ac/Out/NominalInverterPower": {"initial": None, "textformat": _w},
        "/Ac/Out/P": {"initial": 0, "textformat": _w},
        "/Ac/Out/S": {"initial": 0, "textformat": _va},
        # ----
        "/Ac/PowerMeasurementType": {"initial": 4, "textformat": _n},
        "/Ac/State/AcIn1Available": {"initial": 1, "textformat": _n},
        "/Ac/State/IgnoreAcIn1": {"initial": 0, "textformat": _n},
        "/Ac/State/RemoteGeneratorSelected": {"initial": 0, "textformat": _n},
        "/Ac/State/SplitPhaseL2L1OutSummed": {"initial": None, "textformat": _n},
        "/Ac/State/SplitPhaseL2Passthru": {"initial": None, "textformat": _n},
        # ----
        "/AcSensor/0/Current": {"initial": None, "textformat": _a},
        "/AcSensor/0/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/0/Location": {"initial": None, "textformat": _s},
        "/AcSensor/0/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/0/Power": {"initial": None, "textformat": _w},
        "/AcSensor/0/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/1/Current": {"initial": None, "textformat": _a},
        "/AcSensor/1/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/1/Location": {"initial": None, "textformat": _s},
        "/AcSensor/1/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/1/Power": {"initial": None, "textformat": _w},
        "/AcSensor/1/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/2/Current": {"initial": None, "textformat": _a},
        "/AcSensor/2/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/2/Location": {"initial": None, "textformat": _s},
        "/AcSensor/2/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/2/Power": {"initial": None, "textformat": _w},
        "/AcSensor/2/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/3/Current": {"initial": None, "textformat": _a},
        "/AcSensor/3/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/3/Location": {"initial": None, "textformat": _s},
        "/AcSensor/3/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/3/Power": {"initial": None, "textformat": _w},
        "/AcSensor/3/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/4/Current": {"initial": None, "textformat": _a},
        "/AcSensor/4/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/4/Location": {"initial": None, "textformat": _s},
        "/AcSensor/4/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/4/Power": {"initial": None, "textformat": _w},
        "/AcSensor/4/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/5/Current": {"initial": None, "textformat": _a},
        "/AcSensor/5/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/5/Location": {"initial": None, "textformat": _s},
        "/AcSensor/5/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/5/Power": {"initial": None, "textformat": _w},
        "/AcSensor/5/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/6/Current": {"initial": None, "textformat": _a},
        "/AcSensor/6/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/6/Location": {"initial": None, "textformat": _s},
        "/AcSensor/6/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/6/Power": {"initial": None, "textformat": _w},
        "/AcSensor/6/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/7/Current": {"initial": None, "textformat": _a},
        "/AcSensor/7/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/7/Location": {"initial": None, "textformat": _s},
        "/AcSensor/7/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/7/Power": {"initial": None, "textformat": _w},
        "/AcSensor/7/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/8/Current": {"initial": None, "textformat": _a},
        "/AcSensor/8/Energy": {"initial": None, "textformat": _wh},
        "/AcSensor/8/Location": {"initial": None, "textformat": _s},
        "/AcSensor/8/Phase": {"initial": None, "textformat": _n},
        "/AcSensor/8/Power": {"initial": None, "textformat": _w},
        "/AcSensor/8/Voltage": {"initial": None, "textformat": _v},
        "/AcSensor/Count": {"initial": None, "textformat": _n},
        # ----
        "/Alarms/BmsConnectionLost": {"initial": 0, "textformat": _n},
        "/Alarms/BmsPreAlarm": {"initial": None, "textformat": _n},
        "/Alarms/GridLost": {"initial": 0, "textformat": _n},
        "/Alarms/HighDcCurrent": {"initial": 0, "textformat": _n},
        "/Alarms/HighDcVoltage": {"initial": 0, "textformat": _n},
        "/Alarms/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L1/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L1/InverterImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L1/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/L1/MainsImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L1/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/L1/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/L2/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L2/InverterImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L2/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/L2/MainsImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L2/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/L2/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/L3/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L3/InverterImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L3/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/L3/MainsImbalance": {"initial": 0, "textformat": _n},
        "/Alarms/L3/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/L3/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/PhaseRotation": {"initial": 0, "textformat": _n},
        "/Alarms/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/TemperatureSensor": {"initial": 0, "textformat": _n},
        "/Alarms/VoltageSensor": {"initial": 0, "textformat": _n},
        # ----
        "/BatteryOperationalLimits/BatteryLowVoltage": {
            "initial": None,
            "textformat": _v,
        },
        "/BatteryOperationalLimits/MaxChargeCurrent": {
            "initial": None,
            "textformat": _a,
        },
        "/BatteryOperationalLimits/MaxChargeVoltage": {
            "initial": None,
            "textformat": _v,
        },
        "/BatteryOperationalLimits/MaxDischargeCurrent": {
            "initial": None,
            "textformat": _a,
        },
        "/BatterySense/Temperature": {"initial": None, "textformat": _c},
        "/BatterySense/Voltage": {"initial": None, "textformat": _v},
        # ----
        "/Bms/AllowToCharge": {"initial": 1, "textformat": _n},
        "/Bms/AllowToChargeRate": {"initial": 0, "textformat": _n},
        "/Bms/AllowToDischarge": {"initial": 1, "textformat": _n},
        "/Bms/BmsExpected": {"initial": 0, "textformat": _n},
        "/Bms/BmsType": {"initial": 0, "textformat": _n},
        "/Bms/Error": {"initial": 0, "textformat": _n},
        "/Bms/PreAlarm": {"initial": None, "textformat": _n},
        # ----
        "/Dc/0/Current": {"initial": None, "textformat": _a},
        "/Dc/0/MaxChargeCurrent": {"initial": None, "textformat": _a},
        "/Dc/0/Power": {"initial": None, "textformat": _w},
        "/Dc/0/PreferRenewableEnergy": {"initial": None, "textformat": _n},
        "/Dc/0/Temperature": {"initial": None, "textformat": _c},
        "/Dc/0/Voltage": {"initial": None, "textformat": _v},
    }

    # ----
    # Device 0
    # ----
    paths_multiplus_dbus.update(create_device_dbus_paths(0))

    if phase_count >= 2:
        # ----
        # Device 1
        # ----
        paths_multiplus_dbus.update(create_device_dbus_paths(1))

    if phase_count == 3:
        # ----
        # Device 2
        # ----
        paths_multiplus_dbus.update(create_device_dbus_paths(2))

    paths_multiplus_dbus.update(
        {
            # ----
            "/Devices/Bms/Version": {"initial": None, "textformat": _s},
            "/Devices/Dmc/Version": {"initial": None, "textformat": _s},
            "/Devices/NumberOfMultis": {"initial": phase_count, "textformat": _n},
            # ----
            "/Energy/AcIn1ToAcOut": {"initial": None, "textformat": _n},
            "/Energy/AcIn1ToInverter": {"initial": None, "textformat": _n},
            "/Energy/AcIn2ToAcOut": {"initial": None, "textformat": _n},
            "/Energy/AcIn2ToInverter": {"initial": None, "textformat": _n},
            "/Energy/AcOutToAcIn1": {"initial": None, "textformat": _n},
            "/Energy/AcOutToAcIn2": {"initial": None, "textformat": _n},
            "/Energy/InverterToAcIn1": {"initial": None, "textformat": _n},
            "/Energy/InverterToAcIn2": {"initial": None, "textformat": _n},
            "/Energy/InverterToAcOut": {"initial": None, "textformat": _n},
            "/Energy/OutToInverter": {"initial": None, "textformat": _n},
            "/ExtraBatteryCurrent": {"initial": None, "textformat": _n},
            # ----
            "/FirmwareFeatures/BolFrame": {"initial": 1, "textformat": _n},
            "/FirmwareFeatures/BolUBatAndTBatSense": {"initial": 1, "textformat": _n},
            "/FirmwareFeatures/CommandWriteViaId": {"initial": 1, "textformat": _n},
            "/FirmwareFeatures/IBatSOCBroadcast": {"initial": 1, "textformat": _n},
            "/FirmwareFeatures/NewPanelFrame": {"initial": 1, "textformat": _n},
            "/FirmwareFeatures/SetChargeState": {"initial": 1, "textformat": _n},
            "/FirmwareSubVersion": {"initial": 0, "textformat": _n},
            # ----
            "/Hub/ChargeVoltage": {"initial": None, "textformat": _n},
            "/Hub4/AssistantId": {"initial": 5, "textformat": _n},
            "/Hub4/DisableCharge": {"initial": 0, "textformat": _n},
            "/Hub4/DisableFeedIn": {"initial": 0, "textformat": _n},
            "/Hub4/DoNotFeedInOvervoltage": {"initial": 1, "textformat": _n},
            "/Hub4/FixSolarOffsetTo100mV": {"initial": 1, "textformat": _n},
        }
    )

    paths_multiplus_dbus.update(
        {
            # com.victronenergy.settings/Settings/CGwacs/AcPowerSetPoint
            # if positive then same value, if negative value +1
            "/Hub4/L1/AcPowerSetpoint": {"initial": 0, "textformat": _n},
            "/Hub4/L1/CurrentLimitedDueToHighTemp": {"initial": 0, "textformat": _n},
            "/Hub4/L1/FrequencyVariationOccurred": {"initial": 0, "textformat": _n},
            "/Hub4/L1/MaxFeedInPower": {"initial": 32766, "textformat": _n},
            "/Hub4/L1/OffsetAddedToVoltageSetpoint": {"initial": 0, "textformat": _n},
            "/Hub4/L1/OverruledShoreLimit": {"initial": None, "textformat": _n},
        }
    )

    if phase_count >= 2:
        paths_multiplus_dbus.update(
            {
                # com.victronenergy.settings/Settings/CGwacs/AcPowerSetPoint
                # if positive then same value, if negative value +1
                "/Hub4/L2/AcPowerSetpoint": {"initial": 0, "textformat": _n},
                "/Hub4/L2/CurrentLimitedDueToHighTemp": {
                    "initial": 0,
                    "textformat": _n,
                },
                "/Hub4/L2/FrequencyVariationOccurred": {"initial": 0, "textformat": _n},
                "/Hub4/L2/MaxFeedInPower": {"initial": 32766, "textformat": _n},
                "/Hub4/L2/OffsetAddedToVoltageSetpoint": {
                    "initial": 0,
                    "textformat": _n,
                },
                "/Hub4/L2/OverruledShoreLimit": {"initial": None, "textformat": _n},
            }
        )

    if phase_count == 3:
        paths_multiplus_dbus.update(
            {
                # com.victronenergy.settings/Settings/CGwacs/AcPowerSetPoint
                # if positive then same value, if negative value +1
                "/Hub4/L3/AcPowerSetpoint": {"initial": 0, "textformat": _n},
                "/Hub4/L3/CurrentLimitedDueToHighTemp": {
                    "initial": 0,
                    "textformat": _n,
                },
                "/Hub4/L3/FrequencyVariationOccurred": {"initial": 0, "textformat": _n},
                "/Hub4/L3/MaxFeedInPower": {"initial": 32766, "textformat": _n},
                "/Hub4/L3/OffsetAddedToVoltageSetpoint": {
                    "initial": 0,
                    "textformat": _n,
                },
                "/Hub4/L3/OverruledShoreLimit": {"initial": None, "textformat": _n},
            }
        )

    paths_multiplus_dbus.update(
        {
            "/Hub4/Sustain": {"initial": 0, "textformat": _n},
            "/Hub4/TargetPowerIsMaxFeedIn": {"initial": 0, "textformat": _n},
            # ----
            # "/Interfaces/Mk2/Connection": {"initial": "/dev/ttyS3", "textformat": _n},
            # "/Interfaces/Mk2/ProductId": {"initial": 4464, "textformat": _n},
            # "/Interfaces/Mk2/ProductName": {"initial": "MK3", "textformat": _n},
            # "/Interfaces/Mk2/Status/Baudrate": {"initial": 115200, "textformat": _n},
            # "/Interfaces/Mk2/Status/BusFreeMode": {"initial": 1, "textformat": _n},
            # "/Interfaces/Mk2/Tunnel": {"initial": None, "textformat": _n},
            # "/Interfaces/Mk2/Version": {"initial": 1170216, "textformat": _n},
            # ----
            "/Leds/Absorption": {"initial": 0, "textformat": _n},
            "/Leds/Bulk": {"initial": 0, "textformat": _n},
            "/Leds/Float": {"initial": 0, "textformat": _n},
            "/Leds/Inverter": {"initial": 0, "textformat": _n},
            "/Leds/LowBattery": {"initial": 0, "textformat": _n},
            "/Leds/Mains": {"initial": 1, "textformat": _n},
            "/Leds/Overload": {"initial": 0, "textformat": _n},
            "/Leds/Temperature": {"initial": 0, "textformat": _n},
            "/Mode": {"initial": 3, "textformat": _n},
            "/ModeIsAdjustable": {"initial": 1, "textformat": _n},
            "/PvInverter/Disable": {"initial": 1, "textformat": _n},
            "/Quirks": {"initial": 0, "textformat": _n},
            "/RedetectSystem": {"initial": 0, "textformat": _n},
            "/Settings/Alarm/System/GridLost": {"initial": 1, "textformat": _n},
            "/Settings/SystemSetup/AcInput1": {"initial": 1, "textformat": _n},
            "/Settings/SystemSetup/AcInput2": {"initial": 0, "textformat": _n},
            "/ShortIds": {"initial": 1, "textformat": _n},
            "/Soc": {"initial": None, "textformat": _percent},
            "/State": {"initial": 3, "textformat": _n},
            "/SystemReset": {"initial": None, "textformat": _n},
            "/VebusChargeState": {"initial": 1, "textformat": _n},
            "/VebusError": {"initial": 0, "textformat": _n},
            "/VebusMainState": {"initial": 9, "textformat": _n},
            "/VebusSetChargeState": {"initial": 0, "textformat": _n},
            # ----
            "/UpdateIndex": {"initial": 0, "textformat": _n},
        }
    )

    time_driver_started = int(time())

    DbusMultiPlusEmulator(
        servicename="com.victronenergy.vebus.ttyS3",
        deviceinstance=275,
        paths=paths_multiplus_dbus,
    )

    logging.info(
        "Connected to dbus and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
