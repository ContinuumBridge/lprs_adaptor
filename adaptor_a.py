#!/usr/bin/env python
# adaptor_a.py
# Copyright (C) ContinuumBridge Limited, 2015 - All Rights Reserved
# Written by Peter Claydon
#

import sys
import time
import json
import serial
from cbcommslib import CbAdaptor
from cbconfig import *
from twisted.internet import threads
from twisted.internet import reactor

LPRS_TYPE = os.getenv('CB_LPRS_TYPE', 'ERA')

class Adaptor(CbAdaptor):
    def __init__(self, argv):
        self.status =           "ok"
        self.state =            "stopped"
        self.stop = False
        self.apps =             {"rssi": []}
        self.toSend = 0
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
            reactor.callInThread(self.listen)
        except Exception as ex:
            self.cbLog("error", "Problems setting up serial port. Exception: " + str(type(ex)) + ", " + str(ex.args))
        else:
            try:
                # Send RSSI with every packet received
                if LPRS_TYPE == "ERA":
                    self.ser.write("ER_CMD#a01")
                    time.sleep(2)
                    self.ser.write("ACK")
                    time.sleep(2)
                # Set bandwidth to 12.5 KHz
                self.ser.write("ER_CMD#B0")
                time.sleep(2)
                self.ser.write("ACK")
                time.sleep(2)
                reactor.callLater(2, self.sendData)
                self.cbLog("info", "Radio initialised")
            except Exception as ex:
                self.cbLog("warning", "Unable to initialise radio. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def listen(self):
        # Called in thread
        listen_txt = ''
        while not self.doStop:
            while self.ser.inWaiting()>0 and not self.doStop:
                time.sleep(0.005)
                listen_txt += self.ser.read(1)
            if not self.doStop:
                if listen_txt !='':
                    rssi = ord(listen_txt[0])
                    message = listen_txt[1:]
                    self.cbLog("debug",  "rssi: " + str(rssi) + ", message: " + message)
                    self.sendCharacteristic("rssi", rssi, time.time())
                    listen_txt = ''
            time.sleep(0.1)

    def sendData(self):
        try:
            self.toSend = (self.toSend + 1)%256
            dat = str(hex(self.toSend)[2:])
            self.cbLog("debug", "sending: " + dat)
            self.ser.write(dat)
            reactor.callLater(2, self.sendData)
        except Exception as ex:
            self.cbLog("warning", "Unable to send data. Exception: " + str(type(ex)) + ", " + str(ex.args))

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
                "service": [{"characteristic": "rssi",
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

    def onAppCommand(self, message):
        if "data" not in message:
            self.cbLog("warning", "app message without data: " + str(message))
        else:
            self.cbLog("debug", "Message from app: " +  str(message))
            ser.write(message["data"])

    def onConfigureMessage(self, config):
        """Config is based on what apps are to be connected.
            May be called again if there is a new configuration, which
            could be because a new app has been added.
        """
        self.setState("starting")

if __name__ == '__main__':
    adaptor = Adaptor(sys.argv)
