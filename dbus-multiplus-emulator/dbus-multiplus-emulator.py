#!/usr/bin/env python

from gi.repository import GLib
import platform
import logging
import sys
import os
import _thread

# import Victron Energy packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))
from vedbus import VeDbusService
from dbusmonitor import DbusMonitor

# use WARNING for default, INFO for displaying actual steps and values, DEBUG for debugging
logging.basicConfig(level=logging.WARNING)



# enter grid frequency
grid_frequency = 50.0000

# enter the dbusServiceName from which the battery data should be fetched
dbusServiceNameBattery = 'com.victronenergy.battery.zero'

# enter the dbusServiceName from which the grid meter data should be fetched
dbusServiceNameGrid = 'com.victronenergy.grid.mqtt_grid'



class DbusMultiPlusEmulator:

    # create dummy until updated
    batteryValues = {
        '/Dc/0/Current': None,
        '/Dc/0/Power': None,
        '/Dc/0/Temperature': None,
        '/Dc/0/Voltage': None,
        '/Soc': None
    }
    gridValues = {
        '/Ac/Voltage': 230
    }

    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        productname='MultiPlus-II 48/5000/70-50 (emulated)',
        connection='VE.Bus'
    ):

        self._dbusservice = VeDbusService(servicename)
        self._paths = paths

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__) # ok
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version()) # ok
        self._dbusservice.add_path('/Mgmt/Connection', connection) #ok

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance) # ok
        self._dbusservice.add_path('/ProductId', 2623) # ok
        self._dbusservice.add_path('/ProductName', productname) # ok
        self._dbusservice.add_path('/CustomName', '') #ok
        self._dbusservice.add_path('/FirmwareVersion', 1175) # ok
        #self._dbusservice.add_path('/HardwareVersion', '0.0.1')
        self._dbusservice.add_path('/Connected', 1) #ok

        #self._dbusservice.add_path('/Latency', None)
        #self._dbusservice.add_path('/ErrorCode', 0)
        #self._dbusservice.add_path('/Position', 0)
        #self._dbusservice.add_path('/StatusCode', 0)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], writeable=True, onchangecallback=self._handlechangedvalue
                )


        ## read values from battery
        # Why this dummy? Because DbusMonitor expects these values to be there, even though we don't
        # need them. So just add some dummy data. This can go away when DbusMonitor is more generic.
        dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
        dbus_tree = {
            'com.victronenergy.battery': {
                '/Connected': dummy,
                '/ProductName': dummy,
                '/Mgmt/Connection': dummy,
                '/DeviceInstance': dummy,
                '/Dc/0/Current': dummy,
                '/Dc/0/Power': dummy,
                '/Dc/0/Temperature': dummy,
                '/Dc/0/Voltage': dummy,
                '/Soc': dummy,
                #'/Sense/Current': dummy,
                #'/TimeToGo': dummy,
                #'/ConsumedAmphours': dummy,
                #'/ProductId': dummy,
                #'/CustomName': dummy,
                #'/Info/MaxChargeVoltage': dummy
            },
            'com.victronenergy.grid' : {
            #    '/Connected': dummy,
            #    '/ProductName': dummy,
            #    '/Mgmt/Connection': dummy,
            #    '/ProductId' : dummy,
            #    '/DeviceType' : dummy,
            #    '/Ac/L1/Power': dummy,
            #    '/Ac/L2/Power': dummy,
            #    '/Ac/L3/Power': dummy,
            #    '/Ac/L1/Current': dummy,
            #    '/Ac/L2/Current': dummy,
            #    '/Ac/L3/Current': dummy
                '/Ac/Voltage': dummy
            },
        }

        #self._dbusreadservice = DbusMonitor('com.victronenergy.battery.zero')
        self._dbusmonitor = self._create_dbus_monitor(
            dbus_tree,
            valueChangedCallback=self._dbus_value_changed,
            deviceAddedCallback=self._device_added,
            deviceRemovedCallback=self._device_removed
        )

        GLib.timeout_add(1000, self._update) # pause 1000ms before the next request



    def _create_dbus_monitor(self, *args, **kwargs):
        return DbusMonitor(*args, **kwargs)


    def _dbus_value_changed(self, dbusServiceName, dbusPath, dict, changes, deviceInstance):
        self._changed = True

        if dbusServiceName == dbusServiceNameBattery:
            self.batteryValues.update({
                str(dbusPath): changes['Value']
            })

        if dbusServiceName == dbusServiceNameGrid:
            self.gridValues.update({
                str(dbusPath): changes['Value']
            })

        #print('_dbus_value_changed')
        #print(dbusServiceName)
        #print(dbusPath)
        #print(dict)
        #print(changes)
        #print(deviceInstance)

        #print(self.batteryValues)
        #print(self.gridValues)

    def _device_added(self, service, instance, do_service_change=True):

        #print('_device_added')
        #print(service)
        #print(instance)
        #print(do_service_change)

        pass

    def _device_removed(self, service, instance):

        #print('_device_added')
        #print(service)
        #print(instance)

        pass

    def _update(self):

        ac = {
            'current': round(self.batteryValues['/Dc/0/Power']/self.gridValues['/Ac/Voltage']),
            'power': self.batteryValues['/Dc/0/Power'],
            'voltage': self.gridValues['/Ac/Voltage']
        }

        self._dbusservice['/Ac/ActiveIn/ActiveInput'] =  0
        self._dbusservice['/Ac/ActiveIn/Connected'] =  1
        self._dbusservice['/Ac/ActiveIn/CurrentLimit'] =  16
        self._dbusservice['/Ac/ActiveIn/CurrentLimitIsAdjustable'] =  1

        # get values from BMS
        # for bubble flow in chart and load visualization
        self._dbusservice['/Ac/ActiveIn/L1/F'] =  grid_frequency
        self._dbusservice['/Ac/ActiveIn/L1/I'] =  ac['current']
        self._dbusservice['/Ac/ActiveIn/L1/P'] =  ac['power']
        self._dbusservice['/Ac/ActiveIn/L1/S'] =  ac['power']
        self._dbusservice['/Ac/ActiveIn/L1/V'] =  ac['voltage']

        self._dbusservice['/Ac/ActiveIn/L2/F'] =  None
        self._dbusservice['/Ac/ActiveIn/L2/I'] =  None
        self._dbusservice['/Ac/ActiveIn/L2/P'] =  None
        self._dbusservice['/Ac/ActiveIn/L2/S'] =  None
        self._dbusservice['/Ac/ActiveIn/L2/V'] =  None

        self._dbusservice['/Ac/ActiveIn/L3/F'] =  None
        self._dbusservice['/Ac/ActiveIn/L3/I'] =  None
        self._dbusservice['/Ac/ActiveIn/L3/P'] =  None
        self._dbusservice['/Ac/ActiveIn/L3/S'] =  None
        self._dbusservice['/Ac/ActiveIn/L3/V'] =  None

        # get values from BMS
        # for bubble flow in chart and load visualization
        self._dbusservice['/Ac/ActiveIn/P'] =  ac['power']
        self._dbusservice['/Ac/ActiveIn/S'] =  ac['power']

        self._dbusservice['/Ac/In/1/CurrentLimit'] =  16
        self._dbusservice['/Ac/In/1/CurrentLimitIsAdjustable'] =  1

        self._dbusservice['/Ac/In/2/CurrentLimit'] =  None
        self._dbusservice['/Ac/In/2/CurrentLimitIsAdjustable'] =  None

        self._dbusservice['/Ac/NumberOfAcInputs'] =  1
        self._dbusservice['/Ac/NumberOfPhases'] =  1

        self._dbusservice['/Ac/Out/L1/F'] =  grid_frequency
        self._dbusservice['/Ac/Out/L1/I'] =  0
        self._dbusservice['/Ac/Out/L1/P'] =  0
        self._dbusservice['/Ac/Out/L1/S'] =  0
        self._dbusservice['/Ac/Out/L1/V'] =  ac['voltage']

        self._dbusservice['/Ac/Out/L2/F'] =  None
        self._dbusservice['/Ac/Out/L2/I'] =  None
        self._dbusservice['/Ac/Out/L2/P'] =  None
        self._dbusservice['/Ac/Out/L2/S'] =  None
        self._dbusservice['/Ac/Out/L2/V'] =  None

        self._dbusservice['/Ac/Out/L3/F'] =  None
        self._dbusservice['/Ac/Out/L3/I'] =  None
        self._dbusservice['/Ac/Out/L3/P'] =  None
        self._dbusservice['/Ac/Out/L3/S'] =  None
        self._dbusservice['/Ac/Out/L3/V'] =  None

        self._dbusservice['/Ac/Out/P'] =  0
        self._dbusservice['/Ac/Out/S'] =  0

        self._dbusservice['/Ac/PowerMeasurementType'] =  4
        self._dbusservice['/Ac/State/IgnoreAcIn1'] =  0
        self._dbusservice['/Ac/State/SplitPhaseL2Passthru'] =  None

        self._dbusservice['/Alarms/HighDcCurrent'] =  0
        self._dbusservice['/Alarms/HighDcVoltage'] =  0
        self._dbusservice['/Alarms/HighTemperature'] =  0
        self._dbusservice['/Alarms/L1/HighTemperature'] =  0
        self._dbusservice['/Alarms/L1/LowBattery'] =  0
        self._dbusservice['/Alarms/L1/Overload'] =  0
        self._dbusservice['/Alarms/L1/Ripple'] =  0
        self._dbusservice['/Alarms/L2/HighTemperature'] =  0
        self._dbusservice['/Alarms/L2/LowBattery'] =  0
        self._dbusservice['/Alarms/L2/Overload'] =  0
        self._dbusservice['/Alarms/L2/Ripple'] =  0
        self._dbusservice['/Alarms/L3/HighTemperature'] =  0
        self._dbusservice['/Alarms/L3/LowBattery'] =  0
        self._dbusservice['/Alarms/L3/Overload'] =  0
        self._dbusservice['/Alarms/L3/Ripple'] =  0
        self._dbusservice['/Alarms/LowBattery'] =  0
        self._dbusservice['/Alarms/Overload'] =  0
        self._dbusservice['/Alarms/PhaseRotation'] =  0
        self._dbusservice['/Alarms/Ripple'] =  0
        self._dbusservice['/Alarms/TemperatureSensor'] =  0
        self._dbusservice['/Alarms/VoltageSensor'] =  0

        self._dbusservice['/BatteryOperationalLimits/BatteryLowVoltage'] =  46.4
        self._dbusservice['/BatteryOperationalLimits/MaxChargeCurrent'] =  80
        self._dbusservice['/BatteryOperationalLimits/MaxChargeVoltage'] =  55.2
        self._dbusservice['/BatteryOperationalLimits/MaxDischargeCurrent'] =  120
        self._dbusservice['/BatterySense/Temperature'] =  None
        self._dbusservice['/BatterySense/Voltage'] =  None

        self._dbusservice['/Bms/AllowToCharge'] =  1
        self._dbusservice['/Bms/AllowToChargeRate'] =  0
        self._dbusservice['/Bms/AllowToDischarge'] =  1
        self._dbusservice['/Bms/BmsExpected'] =  0
        self._dbusservice['/Bms/BmsType'] =  0
        self._dbusservice['/Bms/Error'] =  0
        self._dbusservice['/Bms/PreAlarm'] =  None

        # get values from BMS
        # for bubble flow in GUI
        self._dbusservice['/Dc/0/Current'] =  self.batteryValues['/Dc/0/Current']
        self._dbusservice['/Dc/0/MaxChargeCurrent'] =  70
        self._dbusservice['/Dc/0/Power'] =  self.batteryValues['/Dc/0/Power']
        self._dbusservice['/Dc/0/Temperature'] =  self.batteryValues['/Dc/0/Temperature']
        self._dbusservice['/Dc/0/Voltage'] =  self.batteryValues['/Dc/0/Voltage']

        #self._dbusservice['/Devices/0/Assistants'] =  0

        self._dbusservice['/Devices/0/ExtendStatus/ChargeDisabledDueToLowTemp'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/ChargeIsDisabled'] =  None
        self._dbusservice['/Devices/0/ExtendStatus/GridRelayReport/Code'] =  None
        self._dbusservice['/Devices/0/ExtendStatus/GridRelayReport/Count'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/GridRelayReport/Reset'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/HighDcCurrent'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/HighDcVoltage'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/IgnoreAcIn1'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/MainsPllLocked'] =  1
        self._dbusservice['/Devices/0/ExtendStatus/PcvPotmeterOnZero'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/PowerPackPreOverload'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/SocTooLowToInvert'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/SustainMode'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/SwitchoverInfo/Connecting'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/SwitchoverInfo/Delay'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/SwitchoverInfo/ErrorFlags'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/TemperatureHighForceBypass'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/VeBusNetworkQualityCounter'] =  0
        self._dbusservice['/Devices/0/ExtendStatus/WaitingForRelayTest'] =  0

        self._dbusservice['/Devices/0/InterfaceProtectionLog/0/ErrorFlags'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/0/Time'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/1/ErrorFlags'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/1/Time'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/2/ErrorFlags'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/2/Time'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/3/ErrorFlags'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/3/Time'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/4/ErrorFlags'] =  None
        self._dbusservice['/Devices/0/InterfaceProtectionLog/4/Time'] =  None

        self._dbusservice['/Devices/0/SerialNumber'] =  'HQ00000AA01'
        self._dbusservice['/Devices/0/Version'] =  2623497

        self._dbusservice['/Devices/Bms/Version'] =  None
        self._dbusservice['/Devices/Dmc/Version'] =  None
        self._dbusservice['/Devices/NumberOfMultis'] =  1

        self._dbusservice['/Energy/AcIn1ToAcOut'] =  0
        self._dbusservice['/Energy/AcIn1ToInverter'] =  0
        self._dbusservice['/Energy/AcIn2ToAcOut'] =  0
        self._dbusservice['/Energy/AcIn2ToInverter'] =  0
        self._dbusservice['/Energy/AcOutToAcIn1'] =  0
        self._dbusservice['/Energy/AcOutToAcIn2'] =  0
        self._dbusservice['/Energy/InverterToAcIn1'] =  0
        self._dbusservice['/Energy/InverterToAcIn2'] =  0
        self._dbusservice['/Energy/InverterToAcOut'] =  0
        self._dbusservice['/Energy/OutToInverter'] =  0
        self._dbusservice['/ExtraBatteryCurrent'] =  0

        self._dbusservice['/FirmwareFeatures/BolFrame'] =  1
        self._dbusservice['/FirmwareFeatures/BolUBatAndTBatSense'] =  1
        self._dbusservice['/FirmwareFeatures/CommandWriteViaId'] =  1
        self._dbusservice['/FirmwareFeatures/IBatSOCBroadcast'] =  1
        self._dbusservice['/FirmwareFeatures/NewPanelFrame'] =  1
        self._dbusservice['/FirmwareFeatures/SetChargeState'] =  1
        self._dbusservice['/FirmwareSubVersion'] =  0

        self._dbusservice['/Hub/ChargeVoltage'] =  55.2
        self._dbusservice['/Hub4/AssistantId'] =  5
        self._dbusservice['/Hub4/DisableCharge'] =  0
        self._dbusservice['/Hub4/DisableFeedIn'] =  0
        self._dbusservice['/Hub4/DoNotFeedInOvervoltage'] =  1
        self._dbusservice['/Hub4/FixSolarOffsetTo100mV'] =  1
        self._dbusservice['/Hub4/L1/AcPowerSetpoint'] =  0
        self._dbusservice['/Hub4/L1/CurrentLimitedDueToHighTemp'] =  0
        self._dbusservice['/Hub4/L1/FrequencyVariationOccurred'] =  0
        self._dbusservice['/Hub4/L1/MaxFeedInPower'] =  32766
        self._dbusservice['/Hub4/L1/OffsetAddedToVoltageSetpoint'] =  0
        self._dbusservice['/Hub4/Sustain'] =  0
        self._dbusservice['/Hub4/TargetPowerIsMaxFeedIn'] =  0

        #'/Interfaces/Mk2/Connection'] =  '/dev/ttyS3'
        #'/Interfaces/Mk2/ProductId'] =  4464
        #'/Interfaces/Mk2/ProductName'] =  'MK3'
        #'/Interfaces/Mk2/Status/BusFreeMode'] =  1
        #'/Interfaces/Mk2/Tunnel'] =  None
        #'/Interfaces/Mk2/Version'] =  1170212

        self._dbusservice['/Leds/Absorption'] =  0
        self._dbusservice['/Leds/Bulk'] =  0
        self._dbusservice['/Leds/Float'] =  0
        self._dbusservice['/Leds/Inverter'] =  0
        self._dbusservice['/Leds/LowBattery'] =  0
        self._dbusservice['/Leds/Mains'] =  0
        self._dbusservice['/Leds/Overload'] =  0
        self._dbusservice['/Leds/Temperature'] =  0

        self._dbusservice['/Mode'] =  3
        self._dbusservice['/ModeIsAdjustable'] =  1
        self._dbusservice['/PvInverter/Disable'] =  0
        self._dbusservice['/Quirks'] =  0
        self._dbusservice['/RedetectSystem'] =  0
        self._dbusservice['/Settings/Alarm/System/GridLost'] =  1
        self._dbusservice['/Settings/SystemSetup/AcInput1'] =  1
        self._dbusservice['/Settings/SystemSetup/AcInput2'] =  0
        self._dbusservice['/ShortIds'] =  1
        self._dbusservice['/Soc'] =  self.batteryValues['/Soc']
        self._dbusservice['/State'] =  8
        self._dbusservice['/SystemReset'] =  None
        self._dbusservice['/VebusChargeState'] =  1
        self._dbusservice['/VebusError'] =  0
        self._dbusservice['/VebusMainState'] =  9


        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice['/UpdateIndex'] + 1  # increment index
        if index > 255:   # maximum value of the index
            index = 0       # overflow from 255 to 0
        self._dbusservice['/UpdateIndex'] = index
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True # accept the change



def main():
    _thread.daemon = True # allow the program to quit

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    paths_dbus = {
        '/Ac/ActiveIn/ActiveInput': {'initial': 0},
        '/Ac/ActiveIn/Connected': {'initial': 1},
        '/Ac/ActiveIn/CurrentLimit': {'initial': 16},
        '/Ac/ActiveIn/CurrentLimitIsAdjustable': {'initial': 1},

        '/Ac/ActiveIn/L1/F': {'initial': 50.1111},
        '/Ac/ActiveIn/L1/I': {'initial': 0},
        '/Ac/ActiveIn/L1/P': {'initial': 0},
        '/Ac/ActiveIn/L1/S': {'initial': 0},
        '/Ac/ActiveIn/L1/V': {'initial': 230.33},

        '/Ac/ActiveIn/L2/F': {'initial': None},
        '/Ac/ActiveIn/L2/I': {'initial': None},
        '/Ac/ActiveIn/L2/P': {'initial': None},
        '/Ac/ActiveIn/L2/S': {'initial': None},
        '/Ac/ActiveIn/L2/V': {'initial': None},

        '/Ac/ActiveIn/L3/F': {'initial': None},
        '/Ac/ActiveIn/L3/I': {'initial': None},
        '/Ac/ActiveIn/L3/P': {'initial': None},
        '/Ac/ActiveIn/L3/S': {'initial': None},
        '/Ac/ActiveIn/L3/V': {'initial': None},

        '/Ac/ActiveIn/P': {'initial': 0},
        '/Ac/ActiveIn/S': {'initial': 0},

        '/Ac/In/1/CurrentLimit': {'initial': 16},
        '/Ac/In/1/CurrentLimitIsAdjustable': {'initial': 1},

        '/Ac/In/2/CurrentLimit': {'initial': None},
        '/Ac/In/2/CurrentLimitIsAdjustable': {'initial': None},

        '/Ac/NumberOfAcInputs': {'initial': 1},
        '/Ac/NumberOfPhases': {'initial': 1},

        '/Ac/Out/L1/F': {'initial': 50.1111},
        '/Ac/Out/L1/I': {'initial': 0},
        '/Ac/Out/L1/P': {'initial': 0},
        '/Ac/Out/L1/S': {'initial': 0},
        '/Ac/Out/L1/V': {'initial': 230.33},

        '/Ac/Out/L2/F': {'initial': None},
        '/Ac/Out/L2/I': {'initial': None},
        '/Ac/Out/L2/P': {'initial': None},
        '/Ac/Out/L2/S': {'initial': None},
        '/Ac/Out/L2/V': {'initial': None},

        '/Ac/Out/L3/F': {'initial': None},
        '/Ac/Out/L3/I': {'initial': None},
        '/Ac/Out/L3/P': {'initial': None},
        '/Ac/Out/L3/S': {'initial': None},
        '/Ac/Out/L3/V': {'initial': None},

        '/Ac/Out/P': {'initial': 0},
        '/Ac/Out/S': {'initial': 0},

        '/Ac/PowerMeasurementType': {'initial': 4},
        '/Ac/State/IgnoreAcIn1': {'initial': 0},
        '/Ac/State/SplitPhaseL2Passthru': {'initial': None},

        '/Alarms/HighDcCurrent': {'initial': 0},
        '/Alarms/HighDcVoltage': {'initial': 0},
        '/Alarms/HighTemperature': {'initial': 0},
        '/Alarms/L1/HighTemperature': {'initial': 0},
        '/Alarms/L1/LowBattery': {'initial': 0},
        '/Alarms/L1/Overload': {'initial': 0},
        '/Alarms/L1/Ripple': {'initial': 0},
        '/Alarms/L2/HighTemperature': {'initial': 0},
        '/Alarms/L2/LowBattery': {'initial': 0},
        '/Alarms/L2/Overload': {'initial': 0},
        '/Alarms/L2/Ripple': {'initial': 0},
        '/Alarms/L3/HighTemperature': {'initial': 0},
        '/Alarms/L3/LowBattery': {'initial': 0},
        '/Alarms/L3/Overload': {'initial': 0},
        '/Alarms/L3/Ripple': {'initial': 0},
        '/Alarms/LowBattery': {'initial': 0},
        '/Alarms/Overload': {'initial': 0},
        '/Alarms/PhaseRotation': {'initial': 0},
        '/Alarms/Ripple': {'initial': 0},
        '/Alarms/TemperatureSensor': {'initial': 0},
        '/Alarms/VoltageSensor': {'initial': 0},

        '/BatteryOperationalLimits/BatteryLowVoltage': {'initial': 46.4},
        '/BatteryOperationalLimits/MaxChargeCurrent': {'initial': 80},
        '/BatteryOperationalLimits/MaxChargeVoltage': {'initial': 55.2},
        '/BatteryOperationalLimits/MaxDischargeCurrent': {'initial': 120},
        '/BatterySense/Temperature': {'initial': None},
        '/BatterySense/Voltage': {'initial': None},

        '/Bms/AllowToCharge': {'initial': 1},
        '/Bms/AllowToChargeRate': {'initial': 0},
        '/Bms/AllowToDischarge': {'initial': 1},
        '/Bms/BmsExpected': {'initial': 0},
        '/Bms/BmsType': {'initial': 0},
        '/Bms/Error': {'initial': 0},
        '/Bms/PreAlarm': {'initial': None},

        '/Dc/0/Current': {'initial': None},
        '/Dc/0/MaxChargeCurrent': {'initial': 70},
        '/Dc/0/Power': {'initial': None},
        '/Dc/0/Temperature': {'initial': None},
        '/Dc/0/Voltage': {'initial': None},

        #'/Devices/0/Assistants': {'initial': 0},

        '/Devices/0/ExtendStatus/ChargeDisabledDueToLowTemp': {'initial': 0},
        '/Devices/0/ExtendStatus/ChargeIsDisabled': {'initial': None},
        '/Devices/0/ExtendStatus/GridRelayReport/Code': {'initial': None},
        '/Devices/0/ExtendStatus/GridRelayReport/Count': {'initial': 0},
        '/Devices/0/ExtendStatus/GridRelayReport/Reset': {'initial': 0},
        '/Devices/0/ExtendStatus/HighDcCurrent': {'initial': 0},
        '/Devices/0/ExtendStatus/HighDcVoltage': {'initial': 0},
        '/Devices/0/ExtendStatus/IgnoreAcIn1': {'initial': 0},
        '/Devices/0/ExtendStatus/MainsPllLocked': {'initial': 1},
        '/Devices/0/ExtendStatus/PcvPotmeterOnZero': {'initial': 0},
        '/Devices/0/ExtendStatus/PowerPackPreOverload': {'initial': 0},
        '/Devices/0/ExtendStatus/SocTooLowToInvert': {'initial': 0},
        '/Devices/0/ExtendStatus/SustainMode': {'initial': 0},
        '/Devices/0/ExtendStatus/SwitchoverInfo/Connecting': {'initial': 0},
        '/Devices/0/ExtendStatus/SwitchoverInfo/Delay': {'initial': 0},
        '/Devices/0/ExtendStatus/SwitchoverInfo/ErrorFlags': {'initial': 0},
        '/Devices/0/ExtendStatus/TemperatureHighForceBypass': {'initial': 0},
        '/Devices/0/ExtendStatus/VeBusNetworkQualityCounter': {'initial': 0},
        '/Devices/0/ExtendStatus/WaitingForRelayTest': {'initial': 0},

        '/Devices/0/InterfaceProtectionLog/0/ErrorFlags': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/0/Time': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/1/ErrorFlags': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/1/Time': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/2/ErrorFlags': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/2/Time': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/3/ErrorFlags': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/3/Time': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/4/ErrorFlags': {'initial': None},
        '/Devices/0/InterfaceProtectionLog/4/Time': {'initial': None},

        '/Devices/0/SerialNumber': {'initial': 'HQ00000AA01'},
        '/Devices/0/Version': {'initial': 2623497},

        '/Devices/Bms/Version': {'initial': None},
        '/Devices/Dmc/Version': {'initial': None},
        '/Devices/NumberOfMultis': {'initial': 1},

        '/Energy/AcIn1ToAcOut': {'initial': 0},
        '/Energy/AcIn1ToInverter': {'initial': 0},
        '/Energy/AcIn2ToAcOut': {'initial': 0},
        '/Energy/AcIn2ToInverter': {'initial': 0},
        '/Energy/AcOutToAcIn1': {'initial': 0},
        '/Energy/AcOutToAcIn2': {'initial': 0},
        '/Energy/InverterToAcIn1': {'initial': 0},
        '/Energy/InverterToAcIn2': {'initial': 0},
        '/Energy/InverterToAcOut': {'initial': 0},
        '/Energy/OutToInverter': {'initial': 0},
        '/ExtraBatteryCurrent': {'initial': 0},

        '/FirmwareFeatures/BolFrame': {'initial': 1},
        '/FirmwareFeatures/BolUBatAndTBatSense': {'initial': 1},
        '/FirmwareFeatures/CommandWriteViaId': {'initial': 1},
        '/FirmwareFeatures/IBatSOCBroadcast': {'initial': 1},
        '/FirmwareFeatures/NewPanelFrame': {'initial': 1},
        '/FirmwareFeatures/SetChargeState': {'initial': 1},
        '/FirmwareSubVersion': {'initial': 0},

        '/Hub/ChargeVoltage': {'initial': 55.2},
        '/Hub4/AssistantId': {'initial': 5},
        '/Hub4/DisableCharge': {'initial': 0},
        '/Hub4/DisableFeedIn': {'initial': 0},
        '/Hub4/DoNotFeedInOvervoltage': {'initial': 1},
        '/Hub4/FixSolarOffsetTo100mV': {'initial': 1},
        '/Hub4/L1/AcPowerSetpoint': {'initial': 0},
        '/Hub4/L1/CurrentLimitedDueToHighTemp': {'initial': 0},
        '/Hub4/L1/FrequencyVariationOccurred': {'initial': 0},
        '/Hub4/L1/MaxFeedInPower': {'initial': 32766},
        '/Hub4/L1/OffsetAddedToVoltageSetpoint': {'initial': 0},
        '/Hub4/Sustain': {'initial': 0},
        '/Hub4/TargetPowerIsMaxFeedIn': {'initial': 0},

        #'/Interfaces/Mk2/Connection': {'initial': '/dev/ttyS3'},
        #'/Interfaces/Mk2/ProductId': {'initial': 4464},
        #'/Interfaces/Mk2/ProductName': {'initial': 'MK3'},
        #'/Interfaces/Mk2/Status/BusFreeMode': {'initial': 1},
        #'/Interfaces/Mk2/Tunnel': {'initial': None},
        #'/Interfaces/Mk2/Version': {'initial': 1170212},

        '/Leds/Absorption': {'initial': 0},
        '/Leds/Bulk': {'initial': 0},
        '/Leds/Float': {'initial': 0},
        '/Leds/Inverter': {'initial': 0},
        '/Leds/LowBattery': {'initial': 0},
        '/Leds/Mains': {'initial': 0},
        '/Leds/Overload': {'initial': 0},
        '/Leds/Temperature': {'initial': 0},

        '/Mode': {'initial': 3},
        '/ModeIsAdjustable': {'initial': 1},
        '/PvInverter/Disable': {'initial': 1},
        '/Quirks': {'initial': 0},
        '/RedetectSystem': {'initial': 0},
        '/Settings/Alarm/System/GridLost': {'initial': 1},
        '/Settings/SystemSetup/AcInput1': {'initial': 1},
        '/Settings/SystemSetup/AcInput2': {'initial': 0},
        '/ShortIds': {'initial': 1},
        '/Soc': {'initial': 0},
        '/State': {'initial': 3},
        '/SystemReset': {'initial': None},
        '/VebusChargeState': {'initial': 1},
        '/VebusError': {'initial': 0},
        '/VebusMainState': {'initial': 9},


        '/UpdateIndex': {'initial': 0},
    }

    pvac_output = DbusMultiPlusEmulator(
        servicename='com.victronenergy.vebus.ttyS3',
        deviceinstance=275,
        paths=paths_dbus
        )

    logging.info('Connected to dbus and switching over to GLib.MainLoop() (= event based)')
    mainloop = GLib.MainLoop()
    mainloop.run()



if __name__ == "__main__":
  main()
