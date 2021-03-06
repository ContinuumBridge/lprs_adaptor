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
import base64
from cbcommslib import CbAdaptor
from cbconfig import *
from twisted.internet import threads
from twisted.internet import reactor

LPRS_TYPE           = os.getenv('CB_LPRS_TYPE', 'ERA')
TX_INTERVAL         = 0.05

class Adaptor(CbAdaptor):
    def __init__(self, argv):
        self.status =           "ok"
        self.state =            "stopped"
        self.stop = False
        self.apps =             {"spur": [],
                                 "rssi": []}
        self.transmitQueue = []
        self.toSend = 0
        self.tracking = {}
        self.count = 0
        self.channel = 0
        self.bandwidth = 0
        self.listening = False
        self.gettingRSSI = False
        self.ackdRSSI = False
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
            except Exception as ex:
                self.cbLog("warning", "Unable to initialise radio. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def listen(self):
        # Called in thread
        self.cbLog("debug", "Starting listen")
        if not self.listening:
            # Set bandwidth to 12.5 KHz
            #self.ser.write("ER_CMD#B0")
            self.ser.write("ER_CMD#B1")
            self.cbLog("info", "Radio initialised")
            self.listening = True
        while not self.doStop:
            try:
                message = ''
                message += self.ser.read(1)
                time.sleep(0.005)
                while self.ser.inWaiting() > 0:
                    time.sleep(0.005)
                    message += self.ser.read(1)
                #reactor.callFromThread(self.cbLog, "debug", "Message received from radio, length:" + str(len(message)))
                if not self.doStop:
                    if message !='':
                        hexMessage = str(message.encode("hex"))
                        reactor.callFromThread(self.cbLog, "debug", "Rx: " + hexMessage)
                        if self.ackdRSSI:
                            try:
                                self.ackdRSSI = False
                                self.gettingRSSI = False
                                rssi = int(message[:message.index("d")])
                                reactor.callFromThread(self.cbLog, "info", "RSSI: {} dBm".format(rssi))
                                reactor.callFromThread(self.sendCharacteristic, "rssi", rssi, time.time())
                            except Exception as ex:
                                self.ackdRSSI = False
                                self.gettingRSSI = False
                                reactor.callFromThread(self.cbLog, "debug", "Problem getting rssi: {}, {}".format(type(ex), ex.args))
                        if message == "ER_CMD#B1":
                            self.ser.write("ACK")
                            reactor.callFromThread(self.cbLog, "info", "Sent ACK for OTA bandwidth")
                            reactor.callLater(1, self.setFrequency)
                        elif self.gettingRSSI:
                            if len(message) == 9:
                                if message == "ER_CMD#T8":
                                    self.ser.write("ACK")
                                    self.ackdRSSI = True
                                    reactor.callFromThread(self.cbLog, "debug", "acknowledged RSSI")
                        elif message[0:8] == "ER_CMD#C":
                            self.ser.write("ACK")
                            reactor.callFromThread(self.cbLog, "info", "Sent ACK for frequency")
                        else:
                            data = base64.b64encode(message)
                            reactor.callFromThread(self.sendCharacteristic, "spur", data, time.time())
                            if message == "Hello World":
                                reactor.callFromThread(self.delaySendHelloButton)
            except Exception as ex:
                reactor.callFromThread(self.cbLog, "warning", "Problem in listen. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def setFrequency(self):
        command = "ER_CMD#C" + str(self.channel)
        self.cbLog("info", "setFrequency, channel command: {}".format(command))
        self.ser.write(command)

    def delaySendHelloButton(self):
        reactor.callLater(0.5, self.sendHelloButton)

    def sendHelloButton(self):
        reactor.callLater(0.5, self.ser.write, "Hello Button")
        self.cbLog("debug", "Sent Hello Button")

    def transmit(self):
        try:
            #self.cbLog("debug", "Tx: " + str(message.encode("hex")))
            if self.transmitQueue:
                self.ser.write(self.transmitQueue[0])
                del self.transmitQueue[0]
            reactor.callLater(TX_INTERVAL, self.transmit)
        except Exception as ex:
            reactor.callFromThread(self.cbLog, "warning", "Problem sending message. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def checkGotRSSI(self):
        # If something went wrong, return a low RSSI. This will still be sent to client with include_req, but bridge will be ignored if more than 1
        if self.gettingRSSI:
            self.sendCharacteristic("rssi", -1000, time.time())
            self.gettingRSSI = False

    def onAppInit(self, message):
        """
        Processes requests from apps.
        Called in a thread and so it is OK if it blocks.
        Called separately for every app that can make requests.
        """
        resp = {
            "name": self.name,
            "id": self.id,
            "status": "ok",
            "service": [
                {
                    "characteristic": "spur",
                    "interval": 0
                },
                {
                    "characteristic": "rssi",
                    "interval": 0
                }
            ],
            "content": "service"
        }
        self.sendMessage(resp, message["id"])
        self.setState("running")
        
    def onAppRequest(self, message):
        self.cbLog("debug", "onAppRequest, message: {}".format(message))
        # Switch off anything that already exists for this app
        for a in self.apps:
            if message["id"] in self.apps[a]:
                self.apps[a].remove(message["id"])
        # Now update details based on the message
        for f in message["service"]:
            if message["id"] not in self.apps[f["characteristic"]]:
                self.apps[f["characteristic"]].append(message["id"])
            if "service" in message:
                for s in message["service"]:
                    if "channel" in s:
                        self.channel = s["channel"]
                    if "bandwidth" in s:
                        self.bandwidth = s["channel"]
        if not self.listening:
            reactor.callInThread(self.listen)
        self.cbLog("debug", "apps: " + str(self.apps))

    def onAppCommand(self, appCommand):
        if "data" in appCommand:
            #self.cbLog("debug", "Tx: Message from app: " +  str(appCommand))
            try:
                self.transmitQueue.append(base64.b64decode(appCommand["data"]))
            except Exception as ex:
                self.cbLog("warning", "Problem formatting message. Exception: " + str(type(ex)) + ", " + str(ex.args))
        elif "command" in appCommand:
            if appCommand["command"] == "get_rssi":
                try:
                    self.gettingRSSI = True
                    reactor.callLater(2, self.checkGotRSSI)
                    self.transmitQueue.append("ER_CMD#T8")
                except Exception as ex:
                    self.cbLog("warning", "Problem ending get RSSI. Exception: " + str(type(ex)) + ", " + str(ex.args))
        else:
            self.cbLog("warning", "invalid app message: {}".format(message))

    def onConfigureMessage(self, config):
        """Config is based on what apps are to be connected.
            May be called again if there is a new configuration, which
            could be because a new app has been added.
        """
        self.setState("starting")
        reactor.callLater(TX_INTERVAL, self.transmit)

if __name__ == '__main__':
    adaptor = Adaptor(sys.argv)
