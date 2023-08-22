#!/usr/bin/env python

from gi.repository import GLib
import platform
import logging
import sys
import os
import _thread
from time import time
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

# enter the dbusServiceName from which the battery data should be fetched, if there is more than one
# e.g. com.victronenergy.battery.mqtt_battery_41
dbusServiceNameBattery = ""

# enter the dbusServiceName from which the grid meter data should be fetched, if there is more than one
# e.g. com.victronenergy.grid.mqtt_grid_31
dbusServiceNameGrid = ""

# specify on which phase the AC PV Inverter is connected
# e.g. L1, L2 or L3
# default: L1
phase = "L1"

# ------------------ USER CHANGABLE VALUES | END --------------------


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
        self._dbusservice.add_path("/FirmwareVersion", 1175)  # ok
        self._dbusservice.add_path("/HardwareVersion", "0.0.3 (20230821)")
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

    def _update(self):
        global data_watt_hours, data_watt_hours_timespan, data_watt_hours_save, data_watt_hours_storage_file, data_watt_hours_working_file, json_data, timestamp_storage_file

        """
        logging.error(
            f'self.gridValues["/Ac/Power"]: {self.gridValues["/Ac/Power"]} and self.batteryValues["/Dc/0/Power"]: {self.batteryValues["/Dc/0/Power"]}'
        )
        #"""
        dc_power = (
            self.batteryValues["/Dc/0/Power"]
            if self.batteryValues["/Dc/0/Power"] is not None
            else 0
        )
        ac_in_power_key = "/Ac/" + phase + "/Power"
        ac_in_power = (
            self.gridValues[ac_in_power_key]
            if self.gridValues[ac_in_power_key] is not None
            else 0
        )
        ac_in_voltage_key = "/Ac/" + phase + "/Voltage"
        ac_in_voltage = (
            self.gridValues[ac_in_voltage_key]
            if self.gridValues[ac_in_voltage_key] is not None
            else 0
        )

        ac_out_power = round(0 - dc_power - ac_in_power)

        ac_in = {
            "current": round(ac_in_power / ac_in_voltage, 2)
            if ac_in_voltage > 0
            else 0,
            "power": ac_in_power,
            "voltage": ac_in_voltage,
        }
        ac_out = {
            "current": round(ac_out_power / ac_in_voltage, 2)
            if ac_in_voltage > 0
            else 0,
            "power": ac_out_power,
            "voltage": ac_in_voltage,
        }

        # ##################################################################################################################

        # # # calculate watthours
        # measure power and calculate watthours, since enphase provides only watthours for production/import/consumption and no export
        # divide charging and discharging from dc
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
                    data_watt_hours["dc"]["charging"] + dc_power_charging
                    if "dc" in data_watt_hours
                    else dc_power_charging,
                    3,
                ),
                "discharging": round(
                    data_watt_hours["dc"]["discharging"] + dc_power_discharging
                    if "dc" in data_watt_hours
                    else dc_power_discharging,
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

        # ##################################################################################################################

        self._dbusservice["/Ac/ActiveIn/ActiveInput"] = 0
        self._dbusservice["/Ac/ActiveIn/Connected"] = 1
        self._dbusservice["/Ac/ActiveIn/CurrentLimit"] = 16
        self._dbusservice["/Ac/ActiveIn/CurrentLimitIsAdjustable"] = 1

        # get values from BMS
        # for bubble flow in chart and load visualization
        # L1 ----
        self._dbusservice["/Ac/ActiveIn/L1/F"] = (
            grid_frequency if phase == "L1" else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/I"] = (
            ac_in["current"] if phase == "L1" else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/P"] = (
            ac_in["power"] if phase == "L1" else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/S"] = (
            ac_in["power"] if phase == "L1" else None
        )
        self._dbusservice["/Ac/ActiveIn/L1/V"] = (
            ac_in["voltage"] if phase == "L1" else None
        )

        # L2 ----
        self._dbusservice["/Ac/ActiveIn/L2/F"] = (
            grid_frequency if phase == "L2" else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/I"] = (
            ac_in["current"] if phase == "L2" else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/P"] = (
            ac_in["power"] if phase == "L2" else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/S"] = (
            ac_in["power"] if phase == "L2" else None
        )
        self._dbusservice["/Ac/ActiveIn/L2/V"] = (
            ac_in["voltage"] if phase == "L2" else None
        )

        # L3 ----
        self._dbusservice["/Ac/ActiveIn/L3/F"] = (
            grid_frequency if phase == "L3" else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/I"] = (
            ac_in["current"] if phase == "L3" else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/P"] = (
            ac_in["power"] if phase == "L3" else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/S"] = (
            ac_in["power"] if phase == "L3" else None
        )
        self._dbusservice["/Ac/ActiveIn/L3/V"] = (
            ac_in["voltage"] if phase == "L3" else None
        )

        # get values from BMS
        # for bubble flow in chart and load visualization
        self._dbusservice["/Ac/ActiveIn/P"] = ac_in["power"]
        self._dbusservice["/Ac/ActiveIn/S"] = ac_in["power"]

        self._dbusservice["/Ac/In/1/CurrentLimit"] = 16
        self._dbusservice["/Ac/In/1/CurrentLimitIsAdjustable"] = 1

        self._dbusservice["/Ac/In/2/CurrentLimit"] = None
        self._dbusservice["/Ac/In/2/CurrentLimitIsAdjustable"] = None

        self._dbusservice["/Ac/NumberOfAcInputs"] = 1
        self._dbusservice["/Ac/NumberOfPhases"] = 1

        # L1 ----
        self._dbusservice["/Ac/Out/L1/F"] = grid_frequency if phase == "L1" else None
        self._dbusservice["/Ac/Out/L1/I"] = ac_out["current"] if phase == "L1" else None
        self._dbusservice["/Ac/Out/L1/NominalInverterPower"] = (
            4500 if phase == "L1" else None
        )
        self._dbusservice["/Ac/Out/L1/P"] = ac_out["power"] if phase == "L1" else None
        self._dbusservice["/Ac/Out/L1/S"] = ac_out["power"] if phase == "L1" else None
        self._dbusservice["/Ac/Out/L1/V"] = ac_out["voltage"] if phase == "L1" else None

        # L2 ----
        self._dbusservice["/Ac/Out/L2/F"] = None if phase == "L2" else None
        self._dbusservice["/Ac/Out/L2/I"] = None if phase == "L2" else None
        self._dbusservice["/Ac/Out/L2/NominalInverterPower"] = (
            4500 if phase == "L2" else None
        )
        self._dbusservice["/Ac/Out/L2/P"] = None if phase == "L2" else None
        self._dbusservice["/Ac/Out/L2/S"] = None if phase == "L2" else None
        self._dbusservice["/Ac/Out/L2/V"] = None if phase == "L2" else None

        # L3 ----
        self._dbusservice["/Ac/Out/L3/F"] = None if phase == "L3" else None
        self._dbusservice["/Ac/Out/L3/I"] = None if phase == "L3" else None
        self._dbusservice["/Ac/Out/L3/NominalInverterPower"] = (
            4500 if phase == "L3" else None
        )
        self._dbusservice["/Ac/Out/L3/P"] = None if phase == "L3" else None
        self._dbusservice["/Ac/Out/L3/S"] = None if phase == "L3" else None
        self._dbusservice["/Ac/Out/L3/V"] = None if phase == "L3" else None

        self._dbusservice["/Ac/Out/NominalInverterPower"] = 4500
        self._dbusservice["/Ac/Out/P"] = ac_out["power"]
        self._dbusservice["/Ac/Out/S"] = ac_out["power"]

        self._dbusservice["/Ac/PowerMeasurementType"] = 4
        self._dbusservice["/Ac/State/IgnoreAcIn1"] = 0
        self._dbusservice["/Ac/State/SplitPhaseL2Passthru"] = None

        self._dbusservice["/Alarms/HighDcCurrent"] = 0
        self._dbusservice["/Alarms/HighDcVoltage"] = 0
        self._dbusservice["/Alarms/HighTemperature"] = 0
        self._dbusservice["/Alarms/L1/HighTemperature"] = 0
        self._dbusservice["/Alarms/L1/LowBattery"] = 0
        self._dbusservice["/Alarms/L1/Overload"] = 0
        self._dbusservice["/Alarms/L1/Ripple"] = 0
        self._dbusservice["/Alarms/L2/HighTemperature"] = 0
        self._dbusservice["/Alarms/L2/LowBattery"] = 0
        self._dbusservice["/Alarms/L2/Overload"] = 0
        self._dbusservice["/Alarms/L2/Ripple"] = 0
        self._dbusservice["/Alarms/L3/HighTemperature"] = 0
        self._dbusservice["/Alarms/L3/LowBattery"] = 0
        self._dbusservice["/Alarms/L3/Overload"] = 0
        self._dbusservice["/Alarms/L3/Ripple"] = 0
        self._dbusservice["/Alarms/LowBattery"] = 0
        self._dbusservice["/Alarms/Overload"] = 0
        self._dbusservice["/Alarms/PhaseRotation"] = 0
        self._dbusservice["/Alarms/Ripple"] = 0
        self._dbusservice["/Alarms/TemperatureSensor"] = 0
        self._dbusservice["/Alarms/VoltageSensor"] = 0

        self._dbusservice["/BatteryOperationalLimits/BatteryLowVoltage"] = None
        self._dbusservice[
            "/BatteryOperationalLimits/MaxChargeCurrent"
        ] = self.batteryValues["/Info/MaxChargeCurrent"]
        self._dbusservice[
            "/BatteryOperationalLimits/MaxChargeVoltage"
        ] = self.batteryValues["/Info/MaxChargeVoltage"]
        self._dbusservice[
            "/BatteryOperationalLimits/MaxDischargeCurrent"
        ] = self.batteryValues["/Info/MaxDischargeCurrent"]
        self._dbusservice["/BatterySense/Temperature"] = None
        self._dbusservice["/BatterySense/Voltage"] = None

        self._dbusservice["/Bms/AllowToCharge"] = 1
        self._dbusservice["/Bms/AllowToChargeRate"] = 0
        self._dbusservice["/Bms/AllowToDischarge"] = 1
        self._dbusservice["/Bms/BmsExpected"] = 0
        self._dbusservice["/Bms/BmsType"] = 0
        self._dbusservice["/Bms/Error"] = 0
        self._dbusservice["/Bms/PreAlarm"] = None

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
            else round(
                self.batteryValues["/Dc/0/Power"] / self.batteryValues["/Dc/0/Current"],
                2,
            )
            if self.batteryValues["/Dc/0/Power"] is not None
            and self.batteryValues["/Dc/0/Current"] is not None
            else None
        )

        # self._dbusservice['/Devices/0/Assistants'] = 0

        self._dbusservice["/Devices/0/ExtendStatus/ChargeDisabledDueToLowTemp"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/ChargeIsDisabled"] = None
        self._dbusservice["/Devices/0/ExtendStatus/GridRelayReport/Code"] = None
        self._dbusservice["/Devices/0/ExtendStatus/GridRelayReport/Count"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/GridRelayReport/Reset"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/HighDcCurrent"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/HighDcVoltage"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/IgnoreAcIn1"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/MainsPllLocked"] = 1
        self._dbusservice["/Devices/0/ExtendStatus/PcvPotmeterOnZero"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/PowerPackPreOverload"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/SocTooLowToInvert"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/SustainMode"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/SwitchoverInfo/Connecting"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/SwitchoverInfo/Delay"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/SwitchoverInfo/ErrorFlags"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/TemperatureHighForceBypass"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/VeBusNetworkQualityCounter"] = 0
        self._dbusservice["/Devices/0/ExtendStatus/WaitingForRelayTest"] = 0

        self._dbusservice["/Devices/0/InterfaceProtectionLog/0/ErrorFlags"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/0/Time"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/1/ErrorFlags"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/1/Time"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/2/ErrorFlags"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/2/Time"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/3/ErrorFlags"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/3/Time"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/4/ErrorFlags"] = None
        self._dbusservice["/Devices/0/InterfaceProtectionLog/4/Time"] = None

        self._dbusservice["/Devices/0/SerialNumber"] = "HQ00000AA01"
        self._dbusservice["/Devices/0/Version"] = 2623497

        self._dbusservice["/Devices/Bms/Version"] = None
        self._dbusservice["/Devices/Dmc/Version"] = None
        self._dbusservice["/Devices/NumberOfMultis"] = 1

        # self._dbusservice["/Energy/AcIn1ToAcOut"] = 0
        # self._dbusservice["/Energy/AcIn1ToInverter"] = 0
        # self._dbusservice["/Energy/AcIn2ToAcOut"] = 0
        # self._dbusservice["/Energy/AcIn2ToInverter"] = 0
        # self._dbusservice["/Energy/AcOutToAcIn1"] = 0
        # self._dbusservice["/Energy/AcOutToAcIn2"] = 0
        # self._dbusservice["/Energy/InverterToAcIn1"] = 0
        # self._dbusservice["/Energy/InverterToAcIn2"] = 0
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
        # self._dbusservice["/ExtraBatteryCurrent"] = 0

        self._dbusservice["/FirmwareFeatures/BolFrame"] = 1
        self._dbusservice["/FirmwareFeatures/BolUBatAndTBatSense"] = 1
        self._dbusservice["/FirmwareFeatures/CommandWriteViaId"] = 1
        self._dbusservice["/FirmwareFeatures/IBatSOCBroadcast"] = 1
        self._dbusservice["/FirmwareFeatures/NewPanelFrame"] = 1
        self._dbusservice["/FirmwareFeatures/SetChargeState"] = 1
        self._dbusservice["/FirmwareSubVersion"] = 0

        self._dbusservice["/Hub/ChargeVoltage"] = 55.2
        self._dbusservice["/Hub4/AssistantId"] = 5
        self._dbusservice["/Hub4/DisableCharge"] = 0
        self._dbusservice["/Hub4/DisableFeedIn"] = 0
        self._dbusservice["/Hub4/DoNotFeedInOvervoltage"] = 1
        self._dbusservice["/Hub4/FixSolarOffsetTo100mV"] = 1
        self._dbusservice["/Hub4/L1/AcPowerSetpoint"] = 0
        self._dbusservice["/Hub4/L1/CurrentLimitedDueToHighTemp"] = 0
        self._dbusservice["/Hub4/L1/FrequencyVariationOccurred"] = 0
        self._dbusservice["/Hub4/L1/MaxFeedInPower"] = 32766
        self._dbusservice["/Hub4/L1/OffsetAddedToVoltageSetpoint"] = 0
        self._dbusservice["/Hub4/Sustain"] = 0
        self._dbusservice["/Hub4/TargetPowerIsMaxFeedIn"] = 0

        # '/Interfaces/Mk2/Connection'] = '/dev/ttyS3'
        # '/Interfaces/Mk2/ProductId'] = 4464
        # '/Interfaces/Mk2/ProductName'] = 'MK3'
        # '/Interfaces/Mk2/Status/BusFreeMode'] = 1
        # '/Interfaces/Mk2/Tunnel'] = None
        # '/Interfaces/Mk2/Version'] = 1170212

        self._dbusservice["/Leds/Absorption"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Absorption") else 0
        )
        self._dbusservice["/Leds/Bulk"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Bulk") else 0
        )
        self._dbusservice["/Leds/Float"] = (
            1 if self.batteryValues["/Info/ChargeMode"].startswith("Float") else 0
        )
        self._dbusservice["/Leds/Inverter"] = 1
        self._dbusservice["/Leds/LowBattery"] = 0
        self._dbusservice["/Leds/Mains"] = 1
        self._dbusservice["/Leds/Overload"] = 0
        self._dbusservice["/Leds/Temperature"] = 0

        self._dbusservice["/Mode"] = 3
        self._dbusservice["/ModeIsAdjustable"] = 1
        self._dbusservice["/PvInverter/Disable"] = 0
        self._dbusservice["/Quirks"] = 0
        self._dbusservice["/RedetectSystem"] = 0
        self._dbusservice["/Settings/Alarm/System/GridLost"] = 1
        self._dbusservice["/Settings/SystemSetup/AcInput1"] = 1
        self._dbusservice["/Settings/SystemSetup/AcInput2"] = 0
        self._dbusservice["/ShortIds"] = 1
        self._dbusservice["/Soc"] = self.batteryValues["/Soc"]
        self._dbusservice["/State"] = 8
        self._dbusservice["/SystemReset"] = None
        self._dbusservice["/VebusChargeState"] = 1
        self._dbusservice["/VebusError"] = 0
        self._dbusservice["/VebusMainState"] = 9

        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index

        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change


def main():
    _thread.daemon = True  # allow the program to quit

    from dbus.mainloop.glib import DBusGMainLoop

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    # formatting
    def _kwh(p, v):
        return str("%.2f" % v) + "kWh"

    def _a(p, v):
        return str("%.2f" % v) + "A"

    def _w(p, v):
        return str("%i" % v) + "W"

    def _va(p, v):
        return str("%i" % v) + "VA"

    def _v(p, v):
        return str("%i" % v) + "V"

    def _hz(p, v):
        return str("%.1f" % v) + "Hz"

    def _c(p, v):
        return str("%i" % v) + "°C"

    def _percent(p, v):
        return str("%.1f" % v) + "%"

    def _n(p, v):
        return str("%i" % v)

    def _s(p, v):
        return str("%s" % v)

    paths_dbus = {
        "/Ac/ActiveIn/ActiveInput": {"initial": 0, "textformat": _n},
        "/Ac/ActiveIn/Connected": {"initial": 1, "textformat": _n},
        "/Ac/ActiveIn/CurrentLimit": {"initial": 16, "textformat": _a},
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
        "/Ac/In/1/CurrentLimit": {"initial": 16, "textformat": _a},
        "/Ac/In/1/CurrentLimitIsAdjustable": {"initial": 1, "textformat": _n},
        # ----
        "/Ac/In/2/CurrentLimit": {"initial": None, "textformat": _a},
        "/Ac/In/2/CurrentLimitIsAdjustable": {"initial": None, "textformat": _n},
        # ----
        "/Ac/NumberOfAcInputs": {"initial": 1, "textformat": _n},
        "/Ac/NumberOfPhases": {"initial": 1, "textformat": _n},
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
        "/Ac/Out/NominalInverterPower": {"initial": 4500, "textformat": _w},
        "/Ac/Out/P": {"initial": 0, "textformat": _w},
        "/Ac/Out/S": {"initial": 0, "textformat": _va},
        # ----
        "/Ac/PowerMeasurementType": {"initial": 4, "textformat": _n},
        "/Ac/State/IgnoreAcIn1": {"initial": 0, "textformat": _n},
        "/Ac/State/SplitPhaseL2Passthru": {"initial": None, "textformat": _n},
        # ----
        "/Alarms/HighDcCurrent": {"initial": 0, "textformat": _n},
        "/Alarms/HighDcVoltage": {"initial": 0, "textformat": _n},
        "/Alarms/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L1/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L1/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/L1/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/L1/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/L2/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L2/LowBattery": {"initial": 0, "textformat": _n},
        "/Alarms/L2/Overload": {"initial": 0, "textformat": _n},
        "/Alarms/L2/Ripple": {"initial": 0, "textformat": _n},
        "/Alarms/L3/HighTemperature": {"initial": 0, "textformat": _n},
        "/Alarms/L3/LowBattery": {"initial": 0, "textformat": _n},
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
        "/Dc/0/Temperature": {"initial": None, "textformat": _c},
        "/Dc/0/Voltage": {"initial": None, "textformat": _v},
        # ----
        # '/Devices/0/Assistants': {'initial': 0, "textformat": _n},
        # ----
        "/Devices/0/ExtendStatus/ChargeDisabledDueToLowTemp": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/ChargeIsDisabled": {"initial": None, "textformat": _n},
        "/Devices/0/ExtendStatus/GridRelayReport/Code": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/GridRelayReport/Count": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/GridRelayReport/Reset": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/HighDcCurrent": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/HighDcVoltage": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/IgnoreAcIn1": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/MainsPllLocked": {"initial": 1, "textformat": _n},
        "/Devices/0/ExtendStatus/PcvPotmeterOnZero": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/PowerPackPreOverload": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/SocTooLowToInvert": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/SustainMode": {"initial": 0, "textformat": _n},
        "/Devices/0/ExtendStatus/SwitchoverInfo/Connecting": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/SwitchoverInfo/Delay": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/SwitchoverInfo/ErrorFlags": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/TemperatureHighForceBypass": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/VeBusNetworkQualityCounter": {
            "initial": 0,
            "textformat": _n,
        },
        "/Devices/0/ExtendStatus/WaitingForRelayTest": {"initial": 0, "textformat": _n},
        # ----
        "/Devices/0/InterfaceProtectionLog/0/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/InterfaceProtectionLog/0/Time": {"initial": None, "textformat": _n},
        "/Devices/0/InterfaceProtectionLog/1/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/InterfaceProtectionLog/1/Time": {"initial": None, "textformat": _n},
        "/Devices/0/InterfaceProtectionLog/2/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/InterfaceProtectionLog/2/Time": {"initial": None, "textformat": _n},
        "/Devices/0/InterfaceProtectionLog/3/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/InterfaceProtectionLog/3/Time": {"initial": None, "textformat": _n},
        "/Devices/0/InterfaceProtectionLog/4/ErrorFlags": {
            "initial": None,
            "textformat": _n,
        },
        "/Devices/0/InterfaceProtectionLog/4/Time": {"initial": None, "textformat": _n},
        # ----
        "/Devices/0/SerialNumber": {"initial": "HQ00000AA01", "textformat": _s},
        "/Devices/0/Version": {"initial": 2623497, "textformat": _s},
        # ----
        "/Devices/Bms/Version": {"initial": None, "textformat": _s},
        "/Devices/Dmc/Version": {"initial": None, "textformat": _s},
        "/Devices/NumberOfMultis": {"initial": 1, "textformat": _n},
        # ----
        "/Energy/AcIn1ToAcOut": {"initial": 0, "textformat": _n},
        "/Energy/AcIn1ToInverter": {"initial": 0, "textformat": _n},
        "/Energy/AcIn2ToAcOut": {"initial": 0, "textformat": _n},
        "/Energy/AcIn2ToInverter": {"initial": 0, "textformat": _n},
        "/Energy/AcOutToAcIn1": {"initial": 0, "textformat": _n},
        "/Energy/AcOutToAcIn2": {"initial": 0, "textformat": _n},
        "/Energy/InverterToAcIn1": {"initial": 0, "textformat": _n},
        "/Energy/InverterToAcIn2": {"initial": 0, "textformat": _n},
        "/Energy/InverterToAcOut": {"initial": 0, "textformat": _n},
        "/Energy/OutToInverter": {"initial": 0, "textformat": _n},
        "/ExtraBatteryCurrent": {"initial": 0, "textformat": _n},
        # ----
        "/FirmwareFeatures/BolFrame": {"initial": 1, "textformat": _n},
        "/FirmwareFeatures/BolUBatAndTBatSense": {"initial": 1, "textformat": _n},
        "/FirmwareFeatures/CommandWriteViaId": {"initial": 1, "textformat": _n},
        "/FirmwareFeatures/IBatSOCBroadcast": {"initial": 1, "textformat": _n},
        "/FirmwareFeatures/NewPanelFrame": {"initial": 1, "textformat": _n},
        "/FirmwareFeatures/SetChargeState": {"initial": 1, "textformat": _n},
        "/FirmwareSubVersion": {"initial": 0, "textformat": _n},
        # ----
        "/Hub/ChargeVoltage": {"initial": 55.2, "textformat": _n},
        "/Hub4/AssistantId": {"initial": 5, "textformat": _n},
        "/Hub4/DisableCharge": {"initial": 0, "textformat": _n},
        "/Hub4/DisableFeedIn": {"initial": 0, "textformat": _n},
        "/Hub4/DoNotFeedInOvervoltage": {"initial": 1, "textformat": _n},
        "/Hub4/FixSolarOffsetTo100mV": {"initial": 1, "textformat": _n},
        "/Hub4/L1/AcPowerSetpoint": {"initial": 0, "textformat": _n},
        "/Hub4/L1/CurrentLimitedDueToHighTemp": {"initial": 0, "textformat": _n},
        "/Hub4/L1/FrequencyVariationOccurred": {"initial": 0, "textformat": _n},
        "/Hub4/L1/MaxFeedInPower": {"initial": 32766, "textformat": _n},
        "/Hub4/L1/OffsetAddedToVoltageSetpoint": {"initial": 0, "textformat": _n},
        "/Hub4/Sustain": {"initial": 0, "textformat": _n},
        "/Hub4/TargetPowerIsMaxFeedIn": {"initial": 0, "textformat": _n},
        # ----
        # '/Interfaces/Mk2/Connection': {'initial': '/dev/ttyS3', "textformat": _n},
        # '/Interfaces/Mk2/ProductId': {'initial': 4464, "textformat": _n},
        # '/Interfaces/Mk2/ProductName': {'initial': 'MK3', "textformat": _n},
        # '/Interfaces/Mk2/Status/BusFreeMode': {'initial': 1, "textformat": _n},
        # '/Interfaces/Mk2/Tunnel': {'initial': None, "textformat": _n},
        # '/Interfaces/Mk2/Version': {'initial': 1170212, "textformat": _n},
        # ----
        "/Leds/Absorption": {"initial": 0, "textformat": _n},
        "/Leds/Bulk": {"initial": 0, "textformat": _n},
        "/Leds/Float": {"initial": 0, "textformat": _n},
        "/Leds/Inverter": {"initial": 1, "textformat": _n},
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
        # ----
        "/UpdateIndex": {"initial": 0, "textformat": _n},
    }

    DbusMultiPlusEmulator(
        servicename="com.victronenergy.vebus.ttyS3",
        deviceinstance=275,
        paths=paths_dbus,
    )

    logging.info(
        "Connected to dbus and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
