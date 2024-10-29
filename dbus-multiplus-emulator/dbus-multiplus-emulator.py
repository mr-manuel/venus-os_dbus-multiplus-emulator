#!/usr/bin/env python

import platform
import logging
import sys
import os
import _thread
from time import sleep, time
from typing import Union
import json
import configparser  # for config/ini file

import dbus
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop


# import Victron Energy packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))
from vedbus import VeDbusService
from vedbus import VeDbusItemImport


# get values from config.ini file
try:
    config_file = (os.path.dirname(os.path.realpath(__file__))) + "/config.ini"
    if os.path.exists(config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
    else:
        print('ERROR:The "' + config_file + '" is not found. Did you copy or rename the "config.sample.ini" to "config.ini"? The driver restarts in 60 seconds.')
        sleep(60)
        sys.exit()

except Exception:
    exception_type, exception_object, exception_traceback = sys.exc_info()
    file = exception_traceback.tb_frame.f_code.co_filename
    line = exception_traceback.tb_lineno
    print(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
    print("ERROR:The driver restarts in 60 seconds.")
    sleep(60)
    sys.exit()


# Get logging level from config.ini
# ERROR = shows errors only
# WARNING = shows ERROR and warnings
# INFO = shows WARNING and running functions
# DEBUG = shows INFO and data/values
if "DEFAULT" in config and "logging" in config["DEFAULT"]:
    if config["DEFAULT"]["logging"] == "DEBUG":
        logging.basicConfig(level=logging.DEBUG)
    elif config["DEFAULT"]["logging"] == "INFO":
        logging.basicConfig(level=logging.INFO)
    elif config["DEFAULT"]["logging"] == "ERROR":
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.WARNING)
else:
    logging.basicConfig(level=logging.WARNING)

# get values from config.ini file
phase_used = config["DEFAULT"]["phase_used"].replace(" ", "").split(",")

inverter_max_power = int(config["DEFAULT"]["inverter_max_power"])
dbus_service_name_grid = config["DEFAULT"]["dbus_service_name_grid"]
dbus_service_name_ac_load = config["DEFAULT"]["dbus_service_name_ac_load"]
grid_frequency = int(config["DEFAULT"]["grid_frequency"])
grid_nominal_voltage = int(config["DEFAULT"]["grid_nominal_voltage"])


# check if the phase_used list is valid
valid_phases = {"L1", "L2", "L3"}
for phase in phase_used:
    if phase not in valid_phases:
        logging.error(f"Invalid phase {phase} in phase_used list. Valid phases are {valid_phases}.")
        sleep(60)
        sys.exit()


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
data_watt_hours_working_file = "/var/volatile/tmp/dbus-multiplus-emulator_data_watt_hours.json"
# get last modification timestamp
timestamp_storage_file = os.path.getmtime(data_watt_hours_storage_file) if os.path.isfile(data_watt_hours_storage_file) else 0

# load data to prevent sending 0 watthours for OutToInverter (charging)/InverterToOut (discharging) before the first loop
# check if file in volatile storage exists
if os.path.isfile(data_watt_hours_working_file):
    with open(data_watt_hours_working_file, "r") as file:
        file = open(data_watt_hours_working_file, "r")
        json_data = json.load(file)
        logging.info("Loaded JSON for OutToInverter (charging)/InverterToOut (discharging) once")
        logging.debug(json.dumps(json_data))
# if not, check if file in persistent storage exists
elif os.path.isfile(data_watt_hours_storage_file):
    with open(data_watt_hours_storage_file, "r") as file:
        file = open(data_watt_hours_storage_file, "r")
        json_data = json.load(file)
        logging.info("Loaded JSON for OutToInverter (charging)/InverterToOut (discharging) once from persistent storage")
        logging.debug(json.dumps(json_data))
else:
    json_data = {}


class DbusMultiPlusEmulator:
    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        productname=(config["DEFAULT"]["device_name"]),
        connection="VE.Bus",
    ):
        self._dbusservice = VeDbusService(servicename, register=False)
        self._paths = paths

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unkown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 2623)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/CustomName", "")
        self._dbusservice.add_path("/FirmwareVersion", 1296)
        self._dbusservice.add_path("/HardwareVersion", "1.0.0-beta1 (20241029)")
        self._dbusservice.add_path("/Connected", 1)

        # self._dbusservice.add_path('/Latency', None)
        # self._dbusservice.add_path('/ErrorCode', 0)
        # self._dbusservice.add_path('/Position', 0)
        # self._dbusservice.add_path('/StatusCode', 0)

        self._dbusservice.add_path("/Ac/ActiveIn/CurrentLimit", 50.0, writeable=True)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                # onchangecallback=self._handlechangedvalue,
            )

        # create empty dictionaries for later use
        self.system_items = {}
        self.grid_items = {}
        self.ac_load_items = {}

        logging.info("-- Initializing completed, starting the main loop")

        # register VeDbusService after all paths where added
        self._dbusservice.register()

        GLib.timeout_add(1000, self._update)  # pause 1000ms before the next request

    def zeroIfNone(self, value: Union[int, float, None]) -> float:
        """
        Returns the value if it is not None, otherwise 0.
        """
        return value if value is not None else 0

    def _update(self):
        global data_watt_hours, data_watt_hours_timespan, data_watt_hours_save
        global data_watt_hours_storage_file, data_watt_hours_working_file, json_data, timestamp_storage_file

        # ##################################################################################################################

        # check for changes in the dbus service list
        # if int(time()) % 15 == 0 or self.system_items == {}:
        #     start = time()
        #     self.system_items, self.grid_items, self.ac_load_items = setup_dbus_external_items()
        #     logging.info("Time to setup external dbus items: %s seconds" % (time() - start))

        # get DC values
        dc_power = self.zeroIfNone(self.system_items["/Dc/Battery/Power"].get_value())
        dc_voltage = self.zeroIfNone(self.system_items["/Dc/Battery/Voltage"].get_value())
        dc_current = self.zeroIfNone(self.system_items["/Dc/Battery/Current"].get_value())

        # # # calculate watthours
        # measure power and calculate watthours, since it provides only watthours for production/import/consumption and no export
        # divide charging and discharging from dc
        # charging (+)
        dc_power_charging = dc_power if dc_power > 0 else 0
        # discharging (-)
        dc_power_discharging = dc_power * -1 if dc_power < 0 else 0

        # timestamp
        timestamp = int(time())

        # sum up values for consumption calculation
        data_watt_hours_dc = {
            "charging": round(
                (data_watt_hours["dc"]["charging"] + dc_power_charging if "dc" in data_watt_hours else dc_power_charging),
                3,
            ),
            "discharging": round(
                (data_watt_hours["dc"]["discharging"] + dc_power_discharging if "dc" in data_watt_hours else dc_power_discharging),
                3,
            ),
        }

        data_watt_hours.update(
            {
                "dc": data_watt_hours_dc,
                "count": data_watt_hours["count"] + 1,
            }
        )

        logging.debug("--> data_watt_hours(): %s" % json.dumps(data_watt_hours))

        # build mean, calculate time diff and Wh and write to file
        # check if at least x seconds are passed
        if data_watt_hours["time_creation"] + data_watt_hours_timespan < timestamp:
            # check if file in volatile storage exists
            if os.path.isfile(data_watt_hours_working_file):
                with open(data_watt_hours_working_file, "r") as file:
                    file = open(data_watt_hours_working_file, "r")
                    data_watt_hours_old = json.load(file)
                    logging.debug("Loaded JSON")
                    logging.debug(json.dumps(data_watt_hours_old))

            # if not, check if file in persistent storage exists
            elif os.path.isfile(data_watt_hours_storage_file):
                with open(data_watt_hours_storage_file, "r") as file:
                    file = open(data_watt_hours_storage_file, "r")
                    data_watt_hours_old = json.load(file)
                    logging.debug("Loaded JSON from persistent storage")
                    logging.debug(json.dumps(data_watt_hours_old))

            # if not, generate data
            else:
                data_watt_hours_old_dc = {
                    "charging": 0,
                    "discharging": 0,
                }
                data_watt_hours_old = {"dc": data_watt_hours_old_dc}
                logging.debug("Generated JSON")
                logging.debug(json.dumps(data_watt_hours_old))

            # factor to calculate Watthours: mean power * measuuring period / 3600 seconds (1 hour)
            factor = (timestamp - data_watt_hours["time_creation"]) / 3600

            dc_charging = round(
                data_watt_hours_old["dc"]["charging"] + (data_watt_hours["dc"]["charging"] / data_watt_hours["count"] * factor) / 1000,
                3,
            )
            dc_discharging = round(
                data_watt_hours_old["dc"]["discharging"] + (data_watt_hours["dc"]["discharging"] / data_watt_hours["count"] * factor) / 1000,
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
                logging.info("Written JSON for OutToInverter (charging)/InverterToOut (discharging) to persistent storage.")

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

            logging.debug("--> data_watt_hours(): %s" % json.dumps(data_watt_hours))

        # update values in dbus
        # for bubble flow in chart and load visualization

        if self.ac_load_items != {}:
            # L1 ----
            if "L1" in phase_used and self.ac_load_items["/Ac/L1/Power"] is not None:
                # power
                self._dbusservice["/Ac/ActiveIn/L1/P"] = self.ac_load_items["/Ac/L1/Power"].get_value()
                self._dbusservice["/Ac/ActiveIn/L1/S"] = self._dbusservice["/Ac/ActiveIn/L1/P"]

                # frequency
                if self.ac_load_items["/Ac/L1/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/F"] = self.ac_load_items["/Ac/L1/Frequency"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L1/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/F"] = self.ac_load_items["/Ac/L1/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/F"] = grid_frequency

                # voltage
                if self.ac_load_items["/Ac/L1/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/V"] = self.ac_load_items["/Ac/L1/Voltage"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L1/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/V"] = self.grid_items["/Ac/L1/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/V"] = grid_nominal_voltage

                # current
                if self.ac_load_items["/Ac/L1/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/I"] = self.ac_load_items["/Ac/L1/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/I"] = round(self._dbusservice["/Ac/ActiveIn/L1/P"] / self._dbusservice["/Ac/ActiveIn/L1/V"], 2)

            # L2 ----
            if "L2" in phase_used and self.ac_load_items["/Ac/L2/Power"] is not None:
                # power
                self._dbusservice["/Ac/ActiveIn/L2/P"] = self.ac_load_items["/Ac/L2/Power"].get_value()
                self._dbusservice["/Ac/ActiveIn/L2/S"] = self._dbusservice["/Ac/ActiveIn/L2/P"]

                # frequency
                if self.ac_load_items["/Ac/L2/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/F"] = self.ac_load_items["/Ac/L2/Frequency"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L2/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/F"] = self.ac_load_items["/Ac/L2/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/F"] = grid_frequency

                # voltage
                if self.ac_load_items["/Ac/L2/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/V"] = self.ac_load_items["/Ac/L2/Voltage"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L2/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/V"] = self.grid_items["/Ac/L2/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/V"] = grid_nominal_voltage

                # current
                if self.ac_load_items["/Ac/L2/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/I"] = self.ac_load_items["/Ac/L2/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/I"] = round(self._dbusservice["/Ac/ActiveIn/L2/P"] / self._dbusservice["/Ac/ActiveIn/L2/V"], 2)

            # L3 ----
            if "L3" in phase_used and self.ac_load_items["/Ac/L3/Power"] is not None:
                # power
                self._dbusservice["/Ac/ActiveIn/L3/P"] = self.ac_load_items["/Ac/L3/Power"].get_value()
                self._dbusservice["/Ac/ActiveIn/L3/S"] = self._dbusservice["/Ac/ActiveIn/L3/P"]

                # frequency
                if self.ac_load_items["/Ac/L3/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/F"] = self.ac_load_items["/Ac/L3/Frequency"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L3/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/F"] = self.ac_load_items["/Ac/L3/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/F"] = grid_frequency

                # voltage
                if self.ac_load_items["/Ac/L3/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/V"] = self.ac_load_items["/Ac/L3/Voltage"].get_value()
                elif self.grid_items != {} and self.grid_items["/Ac/L3/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/V"] = self.grid_items["/Ac/L3/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/V"] = grid_nominal_voltage

                # current
                if self.ac_load_items["/Ac/L3/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/I"] = self.ac_load_items["/Ac/L3/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/I"] = round(self._dbusservice["/Ac/ActiveIn/L3/P"] / self._dbusservice["/Ac/ActiveIn/L3/V"], 2)

        else:
            # calculate ratio of power between each phases
            active_in_L1_power = self.system_items["/Ac/ActiveIn/L1/Power"].get_value() if self.system_items["/Ac/ActiveIn/L1/Power"] is not None else 0
            active_in_L2_power = self.system_items["/Ac/ActiveIn/L2/Power"].get_value() if self.system_items["/Ac/ActiveIn/L2/Power"] is not None else 0
            active_in_L3_power = self.system_items["/Ac/ActiveIn/L3/Power"].get_value() if self.system_items["/Ac/ActiveIn/L3/Power"] is not None else 0

            pv_on_grid_L1_power = self.system_items["/Ac/PvOnGrid/L1/Power"].get_value() if self.system_items["/Ac/PvOnGrid/L1/Power"] is not None else 0
            pv_on_grid_L2_power = self.system_items["/Ac/PvOnGrid/L2/Power"].get_value() if self.system_items["/Ac/PvOnGrid/L2/Power"] is not None else 0
            pv_on_grid_L3_power = self.system_items["/Ac/PvOnGrid/L3/Power"].get_value() if self.system_items["/Ac/PvOnGrid/L3/Power"] is not None else 0

            ac_total_L1_power = self.zeroIfNone(active_in_L1_power) + self.zeroIfNone(pv_on_grid_L1_power)
            ac_total_L2_power = self.zeroIfNone(active_in_L2_power) + self.zeroIfNone(pv_on_grid_L2_power)
            ac_total_L3_power = self.zeroIfNone(active_in_L3_power) + self.zeroIfNone(pv_on_grid_L3_power)
            ac_total_power = ac_total_L1_power + ac_total_L2_power + ac_total_L3_power

            # calculate the ratio of power between each phases
            ratio_L1 = round((ac_total_L1_power / ac_total_power) if ac_total_power != 0 else 0, 4)
            ratio_L2 = round((ac_total_L2_power / ac_total_power) if ac_total_power != 0 else 0, 4)
            ratio_L3 = round((ac_total_L3_power / ac_total_power) if ac_total_power != 0 else 0, 4)

            logging.debug(f"ratio_L1: {ratio_L1}, ratio_L2: {ratio_L2}, ratio_L3: {ratio_L3}")

            # L1 -----
            if "L1" in phase_used:
                # since the MultiPlus emulator is only integrating the power flowing from AC to DC and vice versa, the power is divided by the number of phases
                self._dbusservice["/Ac/ActiveIn/L1/P"] = round((dc_power * ratio_L1 if dc_power != 0 else 0), 0)
                self._dbusservice["/Ac/ActiveIn/L1/S"] = self._dbusservice["/Ac/ActiveIn/L1/P"]

                if self.grid_items != {} and self.grid_items["/Ac/L1/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/F"] = self.grid_items["/Ac/L1/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/F"] = grid_frequency

                # voltage
                if self.grid_items != {} and self.grid_items["/Ac/L1/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/V"] = self.grid_items["/Ac/L1/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/V"] = grid_nominal_voltage

                # current
                if self.grid_items != {} and self.grid_items["/Ac/L1/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L1/I"] = self.grid_items["/Ac/L1/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L1/I"] = round(self._dbusservice["/Ac/ActiveIn/L1/P"] / self._dbusservice["/Ac/ActiveIn/L1/V"], 2)

            # L2 -----
            if "L2" in phase_used:
                # since the MultiPlus emulator is only integrating the power flowing from AC to DC and vice versa, the power is divided by the number of phases
                self._dbusservice["/Ac/ActiveIn/L2/P"] = round((dc_power * ratio_L2 if dc_power != 0 else 0), 0)
                self._dbusservice["/Ac/ActiveIn/L2/S"] = self._dbusservice["/Ac/ActiveIn/L2/P"]

                if self.grid_items != {} and self.grid_items["/Ac/L2/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/F"] = self.grid_items["/Ac/L2/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/F"] = grid_frequency

                # voltage
                if self.grid_items != {} and self.grid_items["/Ac/L2/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/V"] = self.grid_items["/Ac/L2/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/V"] = grid_nominal_voltage

                # current
                if self.grid_items != {} and self.grid_items["/Ac/L2/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L2/I"] = self.grid_items["/Ac/L2/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L2/I"] = round(self._dbusservice["/Ac/ActiveIn/L2/P"] / self._dbusservice["/Ac/ActiveIn/L2/V"], 2)

            # L3 -----
            if "L3" in phase_used:
                # since the MultiPlus emulator is only integrating the power flowing from AC to DC and vice versa, the power is divided by the number of phases
                self._dbusservice["/Ac/ActiveIn/L3/P"] = round((dc_power * ratio_L3 if dc_power != 0 else 0), 0)
                self._dbusservice["/Ac/ActiveIn/L3/S"] = self._dbusservice["/Ac/ActiveIn/L3/P"]

                if self.grid_items != {} and self.grid_items["/Ac/L3/Frequency"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/F"] = self.grid_items["/Ac/L3/Frequency"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/F"] = grid_frequency

                # voltage
                if self.grid_items != {} and self.grid_items["/Ac/L3/Voltage"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/V"] = self.grid_items["/Ac/L3/Voltage"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/V"] = grid_nominal_voltage

                # current
                if self.grid_items != {} and self.grid_items["/Ac/L3/Current"] is not None:
                    self._dbusservice["/Ac/ActiveIn/L3/I"] = self.grid_items["/Ac/L3/Current"].get_value()
                else:
                    self._dbusservice["/Ac/ActiveIn/L3/I"] = round(self._dbusservice["/Ac/ActiveIn/L3/P"] / self._dbusservice["/Ac/ActiveIn/L3/V"], 2)

        # calculate total values
        self._dbusservice["/Ac/ActiveIn/P"] = (
            self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L1/P"]) + self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L2/P"]) + self.zeroIfNone(self._dbusservice["/Ac/ActiveIn/L3/P"])
        )
        self._dbusservice["/Ac/ActiveIn/S"] = self._dbusservice["/Ac/ActiveIn/P"]

        # get values from BMS
        # for bubble flow in chart and load visualization
        self._dbusservice["/Ac/NumberOfPhases"] = phase_count

        # get values from BMS
        # for bubble flow in GUI
        self._dbusservice["/Dc/0/Current"] = dc_current
        # self._dbusservice["/Dc/0/MaxChargeCurrent"] = self.system_items["/Info/MaxChargeCurrent"]
        self._dbusservice["/Dc/0/Power"] = dc_power
        self._dbusservice["/Dc/0/Temperature"] = self.system_items["/Dc/Battery/Temperature"].get_value()
        self._dbusservice["/Dc/0/Voltage"] = dc_voltage

        self._dbusservice["/Devices/0/UpTime"] = int(time()) - time_driver_started

        if phase_count >= 2:
            self._dbusservice["/Devices/1/UpTime"] = int(time()) - time_driver_started

        if phase_count == 3:
            self._dbusservice["/Devices/2/UpTime"] = int(time()) - time_driver_started

        self._dbusservice["/Energy/InverterToAcOut"] = json_data["dc"]["discharging"] if "dc" in json_data and "discharging" in json_data["dc"] else 0
        self._dbusservice["/Energy/OutToInverter"] = json_data["dc"]["charging"] if "dc" in json_data and "charging" in json_data["dc"] else 0

        # self._dbusservice["/Hub/ChargeVoltage"] = self.system_items["/Info/MaxChargeVoltage"]

        # self._dbusservice["/Leds/Absorption"] = 1 if self.system_items["/Info/ChargeMode"].startswith("Absorption") else 0
        # self._dbusservice["/Leds/Bulk"] = 1 if self.system_items["/Info/ChargeMode"].startswith("Bulk") else 0
        # self._dbusservice["/Leds/Float"] = 1 if self.system_items["/Info/ChargeMode"].startswith("Float") else 0
        self._dbusservice["/Soc"] = self.system_items["/Dc/Battery/Soc"].get_value()

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


def setup_dbus_external_items():
    global dbus_service_name_grid, dbus_service_name_ac_load

    # setup external dbus paths
    # connect to the sessionbus, on a CC GX the systembus is used
    dbus_connection = dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus()

    # list of dbus services
    dbus_services = dbus_connection.list_names()

    # ----- BATTERY -----
    # check if the dbus service is available
    dbus_service_system = "com.victronenergy.system"
    is_present_in_vebus = dbus_service_system in dbus_services

    # dictionary containing the different items
    dbus_objects_system = {}

    if is_present_in_vebus:
        dbus_objects_system["/Ac/ActiveIn/L1/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/ActiveIn/L1/Power")
        dbus_objects_system["/Ac/ActiveIn/L2/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/ActiveIn/L2/Power")
        dbus_objects_system["/Ac/ActiveIn/L3/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/ActiveIn/L3/Power")

        dbus_objects_system["/Ac/PvOnGrid/L1/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/PvOnGrid/L1/Power")
        dbus_objects_system["/Ac/PvOnGrid/L2/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/PvOnGrid/L2/Power")
        dbus_objects_system["/Ac/PvOnGrid/L3/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Ac/PvOnGrid/L3/Power")

        dbus_objects_system["/Dc/Battery/BatteryService"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/BatteryService")
        dbus_objects_system["/Dc/Battery/Current"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/Current")
        dbus_objects_system["/Dc/Battery/Power"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/Power")
        dbus_objects_system["/Dc/Battery/Temperature"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/Temperature")
        dbus_objects_system["/Dc/Battery/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/Voltage")
        dbus_objects_system["/Dc/Battery/Soc"] = VeDbusItemImport(dbus_connection, dbus_service_system, "/Dc/Battery/Soc")

    # ----- GRID -----
    is_present_in_vebus = False

    # check if the dbus service is available
    if dbus_service_name_grid != "":
        logging.info(f"Fetched dbus_service_name_grid from config: {dbus_service_name_grid}")
        is_present_in_vebus = dbus_service_name_grid in dbus_services
    # search for the first com.victronenergy.grid service
    else:
        # create variable to store the first grid service name
        dbus_service_name_grid = None

        # iterate through the array to find the first string containing "com.victronenergy.grid"
        for name in dbus_services:
            if "com.victronenergy.grid" in name:
                dbus_service_name_grid = name
                is_present_in_vebus = True
                break

        if dbus_service_name_grid is not None:
            logging.info(f"No grid service name provided, using the first one found: {dbus_service_name_grid}")

    # dictionary containing the different items
    dbus_objects_grid = {}

    if is_present_in_vebus:
        logging.info(f"{dbus_service_name_grid} is present in dbus, setting up the grid values")
        dbus_objects_grid["/Ac/L1/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L1/Power")
        dbus_objects_grid["/Ac/L1/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L1/Current")
        dbus_objects_grid["/Ac/L1/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L1/Voltage")
        dbus_objects_grid["/Ac/L1/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L1/Frequency")

        dbus_objects_grid["/Ac/L2/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L2/Power")
        dbus_objects_grid["/Ac/L2/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L2/Current")
        dbus_objects_grid["/Ac/L2/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L2/Voltage")
        dbus_objects_grid["/Ac/L2/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L2/Frequency")

        dbus_objects_grid["/Ac/L3/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L3/Power")
        dbus_objects_grid["/Ac/L3/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L3/Current")
        dbus_objects_grid["/Ac/L3/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L3/Voltage")
        dbus_objects_grid["/Ac/L3/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/L3/Frequency")

        dbus_objects_grid["/Ac/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/Power")
        dbus_objects_grid["/Ac/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/Current")
        dbus_objects_grid["/Ac/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_grid, "/Ac/Voltage")

    # ----- AC LOAD -----
    is_present_in_vebus = False

    # check if the dbus service is available
    if dbus_service_name_ac_load != "":
        logging.info(f"Fetched dbus_service_name_ac_load from config: {dbus_service_name_ac_load}")
        is_present_in_vebus = dbus_service_name_ac_load in dbus_services
    # search for the first com.victronenergy.acload service
    else:
        # create variable to store the first ac load service name
        dbus_service_name_ac_load = None

        # iterate through the array to find the first string containing "com.victronenergy.acload"
        for name in dbus_services:
            if "com.victronenergy.acload" in name:
                dbus_service_name_ac_load = name
                is_present_in_vebus = True
                break

        if dbus_service_name_ac_load is not None:
            logging.info(f"No AC Load service name provided, using the first one found: {dbus_service_name_ac_load}")

    # dictionary containing the different items
    dbus_objects_ac_load = {}

    if is_present_in_vebus:
        logging.info(f"{dbus_service_name_ac_load} is present in dbus, setting up the ac load values")
        dbus_objects_ac_load["/Ac/L1/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L1/Power")
        dbus_objects_ac_load["/Ac/L1/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L1/Current")
        dbus_objects_ac_load["/Ac/L1/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L1/Voltage")
        dbus_objects_ac_load["/Ac/L1/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L1/Frequency")

        dbus_objects_ac_load["/Ac/L2/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L2/Power")
        dbus_objects_ac_load["/Ac/L2/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L2/Current")
        dbus_objects_ac_load["/Ac/L2/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L2/Voltage")
        dbus_objects_ac_load["/Ac/L2/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L2/Frequency")

        dbus_objects_ac_load["/Ac/L3/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L3/Power")
        dbus_objects_ac_load["/Ac/L3/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L3/Current")
        dbus_objects_ac_load["/Ac/L3/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L3/Voltage")
        dbus_objects_ac_load["/Ac/L3/Frequency"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/L3/Frequency")

        dbus_objects_ac_load["/Ac/Power"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/Power")
        dbus_objects_ac_load["/Ac/Current"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/Current")
        dbus_objects_ac_load["/Ac/Voltage"] = VeDbusItemImport(dbus_connection, dbus_service_name_ac_load, "/Ac/Voltage")

    logging.info("*** Found values ***")

    if dbus_service_system != "":
        logging.info(f"Dbus system service name: {dbus_service_system}")
        for item in dbus_objects_system:
            # remove items that does not exist
            if dbus_objects_system[item].exists:
                logging.info(f"{item} = {dbus_objects_system[item].get_value()}")
            else:
                dbus_objects_system[item] = None
                logging.debug(f"{item} does not exist, removed from grid values")

    if dbus_service_name_grid != "":
        logging.info(f"Dbus grid service name: {dbus_service_name_grid}")
        for item in dbus_objects_grid:
            # remove items that does not exist
            if dbus_objects_grid[item].exists:
                logging.info(f"{item} = {dbus_objects_grid[item].get_value()}")
            else:
                dbus_objects_grid[item] = None
                logging.debug(f"{item} does not exist, removed from grid values")

    if dbus_service_name_ac_load != "":
        logging.info(f"Dbus ac load service name: {dbus_service_name_ac_load}")
        for item in dbus_objects_ac_load:
            # remove items that does not exist
            if dbus_objects_ac_load[item].exists:
                logging.info(f"{item} = {dbus_objects_ac_load[item].get_value()}")
            else:
                dbus_objects_ac_load[item] = None
                logging.debug(f"{item} does not exist, removed from ac_load values")

    return dbus_objects_system, dbus_objects_grid, dbus_objects_ac_load


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

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    paths_multiplus_dbus = {
        "/Ac/ActiveIn/ActiveInput": {"initial": 0, "textformat": _n},
        "/Ac/ActiveIn/Connected": {"initial": 1, "textformat": _n},
        # "/Ac/ActiveIn/CurrentLimit": {"initial": 50.0, "textformat": _a},  # needs also a min and max value
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
        "/Ac/Out/P": {"initial": None, "textformat": _w},
        "/Ac/Out/S": {"initial": None, "textformat": _va},
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

    # has to be called before DbusMultiPlusEmulator() else it does not work
    system_items, grid_items, ac_load_items = setup_dbus_external_items()

    dbus_multiplus_emulator = DbusMultiPlusEmulator(
        servicename="com.victronenergy.vebus.ttyS3",
        deviceinstance=275,
        paths=paths_multiplus_dbus,
    )

    dbus_multiplus_emulator.system_items = system_items
    dbus_multiplus_emulator.grid_items = grid_items
    dbus_multiplus_emulator.ac_load_items = ac_load_items

    logging.info("Connected to dbus and switching over to GLib.MainLoop() (= event based)")
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
