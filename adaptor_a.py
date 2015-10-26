#!/usr/bin/env python
# adaptor_a.py
# Copyright (C) ContinuumBridge Limited, 2015 - All Rights Reserved
# Written by Peter Claydon
#

import sys
import time
import json
import serial
import struct
from cbcommslib import CbAdaptor
from cbconfig import *
from twisted.internet import threads
from twisted.internet import reactor

LPRS_TYPE = os.getenv('CB_LPRS_TYPE', 'ERA')
GALVANIZE_TYPE = os.getenv('CB_GALVANIZE_TYPE', 'BRIDGE')
GALVANIZE_ADDRESS = os.getenv('CB_GALVANIZE_ADDRESS', '0x0000')
WAKEUPINTERVAL = 360

FUNCTIONS = {
    "beacon": 0xBE,
    "woken_up": 0xAA,
    "ack": 0xAC,
    "include_req": 0x00,
    "include_grant": 0x02,
    "reinclude": 0x04,
    "config": 0x05,
    "send_battery": 0x07,
    "alert": 0xAE,
    "battery_status": 0xBA
}

class Adaptor(CbAdaptor):
    def __init__(self, argv):
        self.status =           "ok"
        self.state =            "stopped"
        self.stop = False
        self.apps =             {"galvanize_button": []}
        self.toSend = 0
        self.tracking = {}
        reactor.callLater(0.5, self.initRadio)
        # super's __init__ must be called:
        #super(Adaptor, self).__init__(argv)
        CbAdaptor.__init__(self, argv)

    def setState(self, action):
        # error is only ever set from the running state, so set back to running if error is cleared
        if action == "error":
            self.state == "error"
        elif action == "clear_error":
            self.state = "running"
        else:
            self.state = action
        msg = {"id": self.id,
               "status": "state",
               "state": self.state}
        self.sendManagerMessage(msg)

    def sendCharacteristic(self, characteristic, data, timeStamp):
        msg = {"id": self.id,
               "content": "characteristic",
               "characteristic": characteristic,
               "data": data,
               "timeStamp": timeStamp}
        for a in self.apps[characteristic]:
            self.sendMessage(msg, a)

    def initRadio(self):
        try:
            self.ser = serial.Serial(
                port='/dev/ttyUSB0',
                baudrate= 19200,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout = 0.5
            )
        except Exception as ex:
            self.cbLog("error", "Problems setting up serial port. Exception: " + str(type(ex)) + ", " + str(ex.args))
        else:
            try:
                # Send RSSI with every packet received
                """
                if LPRS_TYPE == "ERA":
                    self.ser.write("ER_CMD#a01")
                    time.sleep(2)
                    self.ser.write("ACK")
                    time.sleep(2)
                """
                self.ser.write("ER_CMD#a00")
                time.sleep(2)
                self.ser.write("ACK")
                time.sleep(2)
                # Set bandwidth to 12.5 KHz
                self.ser.write("ER_CMD#B0")
                time.sleep(2)
                self.ser.write("ACK")
                self.cbLog("info", "Radio initialised")
                reactor.callInThread(self.listen)
            except Exception as ex:
                self.cbLog("warning", "Unable to initialise radio. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def listen(self):
        # Called in thread
        while not self.doStop:
            if True:
            #try:
                message = self.ser.read(256)
                #reactor.callFromThread(self.cbLog, "debug", "Message received from radio, length:" + str(len(message)))
                if not self.doStop:
                    if message !='':
                        destination = struct.unpack(">H", message[0:2])[0]
                        reactor.callFromThread(self.cbLog, "debug", "destination: " + str("{0:#0{1}X}".format(destination,6)))
                        if destination == GALVANIZE_ADDRESS:
                            source, function, length = struct.unpack(">HBB", message[2:6])
                            reactor.callFromThread(self.cbLog, "debug", "source: " + str("{0:#0{1}X}".format(source,6)))
                            reactor.callFromThread(self.cbLog, "debug", "function: " + str("{0:#0{1}X}".format(function,4)))
                            reactor.callFromThread(self.cbLog, "debug", "length: " + str(length))
                            if GALVANIZE_TYPE == "NODE":
                                wakeup = struct.unpack(">H", message[6:8])[0]
                                reactor.callFromThread(self.cbLog, "debug", "wakeup: " + str(wakeup))
                                payload = message[8:][0]
                            else:
                                wakeup = 0
                                payload = message[6:][0]
                            reactor.callFromThread(self.cbLog, "debug", "payload: " + str(payload))
                            f = (key for key,value in FUNCTIONS.items() if value==function).next()
                            characteristic = {
                                "function": f,
                                "wakeup": wakeup,
                                "data": payload
                            }
                            reactor.callFromThread(self.sendCharacteristic, "galvanize_button", characteristic, time.time())
                            reactor.callFromThread(self.cbLog, "debug", "characteriztic: " + str(characteristic))
                        elif destination = BEACON_ADDRESS:
            #except Exception as ex:
            #    self.cbLog("warning", "Problem in listen. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def transmitThread(self, message):
        try:
            self.ser.write(message)
        except Exception as ex:
            self.cbLog("warning", "Problem sending message. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def transmit(self, message):
        reactor.callInThread(self.transmitThread, message)

    def onAppInit(self, message):
        """
        Processes requests from apps.
        Called in a thread and so it is OK if it blocks.
        Called separately for every app that can make requests.
        """
        tagStatus = "ok"
        resp = {"name": self.name,
                "id": self.id,
                "status": tagStatus,
                "service": [{"characteristic": "galvanize_button",
                             "interval": 0}
                            ],
                "content": "service"}
        self.sendMessage(resp, message["id"])
        self.setState("running")
        
    def onAppRequest(self, message):
        # Switch off anything that already exists for this app
        for a in self.apps:
            if message["id"] in self.apps[a]:
                self.apps[a].remove(message["id"])
        # Now update details based on the message
        for f in message["service"]:
            if message["id"] not in self.apps[f["characteristic"]]:
                self.apps[f["characteristic"]].append(message["id"])
        self.cbLog("debug", "apps: " + str(self.apps))

    def onAppCommand(self, appCommand):
        if "data" not in appCommand:
            self.cbLog("warning", "app message without data: " + str(message))
        else:
            self.cbLog("debug", "Message from app: " +  str(appCommand))
            data = appCommand["data"]
            try:
                m = ""
                m += struct.pack(">H", data["destination"])
                m += struct.pack(">H", GALVANIZE_ADDRESS)
                m+= struct.pack("B", FUNCTIONS[data["function"]])
                m+= struct.pack("B", 0)  # Placeholder for length
                if GALVANIZE_TYPE == "BRIDGE":
                    m+= struct.pack(">H", WAKEUPINTERVAL)
                if "data" in data:
                    m += data["data"]
                length = struct.pack("B", len(m))
                message = m[:5] + length + m[6:]
            except Exception as ex:
                self.cbLog("warning", "Problem formatting message. Exception: " + str(type(ex)) + ", " + str(ex.args))
            else:
                self.transmit(message)
                self.cbLog("debug", "message sent")

    def onConfigureMessage(self, config):
        """Config is based on what apps are to be connected.
            May be called again if there is a new configuration, which
            could be because a new app has been added.
        """
        self.cbLog("debug", "GALVANIZE_TYPE: " + GALVANIZE_TYPE)
        self.setState("starting")

if __name__ == '__main__':
    adaptor = Adaptor(sys.argv)
