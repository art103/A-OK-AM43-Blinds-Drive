#!/usr/bin/env python3
# To install libraries needed:
# sudo pip3 install Flask, bluepy, retrying
# Version 1.0 - Bas Bahlmann - The Netherlands

#curl -i http://localhost:5000/Close
#curl -i http://localhost:5000/Open

from bluepy import btle
import configparser
import os
from flask import Flask
import datetime
from retrying import retry

# Startup sequence:
# TX: Login 0000
# RX: AckERR
# TX: Login 8888
# RX: AckOK

# TX: IdPosition 0x01
# RX: IdPosition
# RX: IdPosition2
# RX: IdPosition3
# TX: AckOK

# TX: 0x14  05 07 34 39
# RX: AckOK

# Reverse direction
# TX: 0x11  36 32 00 00 00 00
# RX: AckOK

# Set Upper Boundary
# TX: IdSetLimits  00 01 00
# RX: AckOK
# TX: IdManualMove  dd
# RX: AckOK
# Wait until blind at correct position
# TX: IdManualMove  cc
# RX: AckOK
# RX: IdLimits 00 64 00 00
# TX: AckOK
# TX: IdSetLimits  20 01 00
# RX: AckSet

# Set Lower Boundary
# TX: IdSetLimits 00 02 00
# RX: AckOK
# TX: IdManualMove  ee
# RX: AckOK
# Wait until blind at correct position
# TX: IdManualMove  cc
# RX: AckOK
# RX: IdLimits 00 64 00 00
# TX: AckOK
# TX: IdSetLimits  20 02 00
# RX: AckSet



# Msg format: 9a <id> <len> <data * len> <xor csum>

# 1-byte, 0xdd for setting upper, 0xcc for stop, 0xee for setting lower
IdMoveManual = 0x0a
# 1-byte, 0-100 to set target value in %
IdMoveAuto = 0x0d
# 6-bytes,
IdSettings = 0x11
# 2-bytes with PIN (e.g. 8888 == 22 b8)
IdLogin = 0x17
# 3-bytes <set / save> <channel> 00, <set / save> = 00 / 20, <channel> = 1 / 2 (upper / lower)
IdSetLimits = 0x22

# RX: 4 bytes, 00 64 00 00 (Upper, Lower?)
IdLimits = 0xa1
# RX:
IdBattery = 0xa2
# TX: 1 byte (any value?), RX: 7 bytes, 0e 32 <pos> 00 00 00 30, where <pos> is 0-100
IdPosition = 0xa7
# RX: 0 bytes
IdPosition2 = 0xa8
# RX: 10 bytes, not sure of content yet, possibly reverse, dot, etc.
IdPosition3 = 0xa9
# TX: 1 byte (any value?), RX:
IdLight = 0xaa

# Command Response codes
AckOK = 0x5a
AckSet = 0x5b
AckERR = 0xa5


#Variables
config = configparser.ConfigParser() #Read ini file for meters
config.read('.//AOK-AM43.ini')
app = Flask(__name__)

g_batt = 0
g_pos = 0
g_light = 0

class AM43Delegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)
    def handleNotification(self, cHandle, data):
        global g_batt
        global g_pos
        global g_light
        print("RX:" + "".join("{:02x} ".format(x) for x in data))
        if (data[1] == IdBattery):
            print("Battery: " + str(data[7]) + "%")
            g_batt = data[7]
        elif (data[1] == IdPosition):
            print("Position: " + str(data[5]) + "%")
            g_pos = data[5]
        elif (data[1] == IdLight):
            print("Light: " + str(data[3]) + "%")
            g_light = data[3]


# Constructs message and writes to device
def write_message(dev, id, data):
    ret = False

    # Construct message
    msg = bytearray({0x9a})
    msg += bytearray({id})
    msg += bytearray({len(data)})
    msg += bytearray(data)

    # Calculate checksum (xor)
    csum = 0
    for x in msg:
        csum = csum ^ x
    msg += bytearray({csum})

    print("TX:" + "".join("{:02x} ".format(x) for x in msg))

    service = dev.getServiceByUUID("fe50")
    if (service):
        characteristic = service.getCharacteristics("fe51")[0]
        if (characteristic):
            result = characteristic.write(msg)

            if (result["rsp"][0] == "wr"):
                ret = True
                dev.waitForNotifications(1.0)
    return ret


@retry(stop_max_attempt_number=2,wait_fixed=3000)
def ConnectBTLEDevice(AM43BlindsDeviceMacAddress):
    try:
        print(datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " Connecting to " + AM43BlindsDeviceMacAddress + "...", flush=True)
        dev = btle.Peripheral(AM43BlindsDeviceMacAddress)
        dev.withDelegate(AM43Delegate())
        return dev
    except:
        raise ValueError(datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " Cannot connect to " + AM43BlindsDeviceMacAddress + " trying again....")


@app.route("/")
def hello():
    return "A-OK AM43 BLE Smart Blinds Drive Service\n\n"



@app.route("/<BlindsAction>",methods=['GET'])
def AM43BlindsAction(BlindsAction):
    global g_batt
    global g_pos
    global g_light

    #Code#
    for AM43BlindsDevice in config['AM43_BLE_Devices']:
        result = False
        AM43BlindsDeviceMacAddress = config.get('AM43_BLE_Devices', AM43BlindsDevice)  # Read BLE MAC from ini file
        try:
            dev = ConnectBTLEDevice(AM43BlindsDeviceMacAddress)
        except:
            print(datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " ERROR, Cannot connect to " + AM43BlindsDeviceMacAddress, flush=True)
            continue

        print(datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " --> Connected to " + dev.addr, flush=True)

        if (BlindsAction == "Open"):
            result = write_message(dev, IdMoveAuto, [0])
        elif (BlindsAction == "Close"):
            result = write_message(dev, IdMoveAuto, [100])
        elif (BlindsAction == "Stop"):
            result = write_message(dev, IdMoveManual, [0xcc])
        else:
            result = True

        result = write_message(dev, IdMoveAuto, [100])
        result = write_message(dev, IdMoveManual, [0xcc])

        if (result == True):
            # Always gather the status
            result = write_message(dev, IdBattery, [0x01])
            result = write_message(dev, IdLight, [0x01])
            result = write_message(dev, IdPosition, [0x01])
            dev.waitForNotifications(1.0)
            dev.waitForNotifications(1.0)
            result = write_message(dev, IdPosition, [AckOK])

        # Close connection to BLE device
        dev.disconnect()

    if (result):
        return "Battery: " + str(g_batt) + "%<BR/>Position: " + str(g_pos) + "%<BR/>Light: " + str(g_light) + "%<BR/>"
    else:
        return "ERROR\n"


if __name__ == "__main__":
    AM43BlindsAction("Status")
    #os.system('clear')  # Clear screen
    #app.run(host='0.0.0.0') #Listen to all interfaces  #,debug=True
