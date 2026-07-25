#Serial Manager for WINDOWS

#Developed and maintained by diogo.martins@insidelimits.pt

#Custom built library for serial communcation to be used on functional testing software.

#LVS :: SYSTEM LEVEL INTERACTION, RAISES SYSTEM EXCEPTIONS ON FAILURE
#LV0 :: PERFORMS ACTION WITHOUT ANY VALIDATION OR UI Updates
#LV1 :: PERFORMS ACTION PLUS VALIDATION WITHOUT UI Updates
#LV2 :: PERFORMS ACTION PLUS VALIDATION WITHOUT UI UPDATES, HAS INBUILT RETRIAL
#LV3 :: PERFORMS ACTION PLUS VALIDATION AND UI UPDATES, HAS INBUILT RETRIAL, KILLS INDEX

#LT :: LINE TERMINATOR, EXPECTS \n THE END OF RECEIVED MESSAGE

import TestData
import UIManager

from os import listdir
from os.path import isfile, join
import serial
import serial.tools.list_ports
import time
import array
import asyncio

#MAX nº of ports: 20

portlist = [None] * 20

#port[0] => COM0
#port[1] => COM1
# (...)
#port[19] => COM19

#<CONFIG METHOD> reset portlist list to [None]*20
def RESETPORTLIST(line, UI):

	#0      1
	#WinSerial RESETPORTLIST

	global portlist

	UI.addToLbox("Resetting Port list..")

	portlist = [None] * 20

#<CONFIG METHOD> find ttyUSBx port and asign it to portlist
def FINDPORT(line, UI):

	#0           1          2                  3           4
	#WinSerial   FINDPORT   baudrate,timeout   SER         ID

	global portlist

	UI.addToLbox("Finding COM Port with SER=" + line[3] + ". And assigning it to ID " + line[4])

	portinfo = line[2].split(',')
	baudrate = int(portinfo[0])
	timeout = float(portinfo[1])

	ports = serial.tools.list_ports.comports()

	for port, desc, hwid in sorted(ports):

		temp_ID = hwid[26:len(hwid)]

		if(temp_ID == line[3]):

			#portlist[int(3:len(port))] = {"ID": line[4], "Port": openPort(port, baudrate, timeout)}
			portlist[int(port[3:len(port)])] = {"ID": line[4], "Port": openPort(port, baudrate, timeout)}

			UI.addToLbox("Port found!")

			return

	UI.addToLbox("Port NOT found!")

	raise Exception(line[7] + "::" + "Port NOT found!")

#Open a SerialPort, if it is already open, close and open it
def OPEN(line, UI):

	#0      1    2
	#Serial OPEN ID

	try:

		ID = TestData.getContent(line[2])

		port = getPort(ID)

		if(port.isOpen()):

			port.close()
			port.open()

	except Exception as e:

		 raise Exception(line[7] + "::" + str(e))

#Close a SerialPort if it is open
def CLOSE(line, UI):

	#0      1     2
	#Serial CLOSE ID

	try:

		ID = TestData.getContent(line[2])

		port = getPort(ID)

		if(port.isOpen()):

			port.close()

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))


#**************************************************************WRITE********************************************************************

#SEND STRING
async def WRITE(line, UI):

	#0      1             2       3
	#Serial WRITE_LV0     ID      MESSAGE

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3])

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")
		port.write(MESSAGE.encode())

	except:

		raise Exception(line[7] + "::" + str(e))

#SEND STRING + \n
async def WRITELINE(line, UI):

	#0      1                 2       3
	#Serial WRITELINE_LV0     ID      MESSAGE

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3]) + '\n'

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")
		port.write(MESSAGE.encode())

	except:

		raise Exception(line[7] + "::" + str(e))

#SEND BYTES, SEND BYTE ARRAY
async def WRITEBYTES(line, UI):

	#0      1              2       3
	#Serial WRITEBYTES     ID      MESSAGE_ARRAY
	#Serial WRITEBYTES     BASE    79,75,13,10
	#Serial WRITEBYTES     BASE    79,75,13,10

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')

		port = getPort(ID)

		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		port.write(bytearray(byte_array_write))

	except:

		raise Exception(line[7] + "::" + str(e))

#***************************************************************************************************************************************

#**************************************************************READ*********************************************************************

#LV0

#RECEIVE STRING TERMINATED WITH \n AND SAVES ITS CONTENTS
async def READLINE_LV0(line, UI):

	#0      1                   2       4         5		6
	#Serial RECEIVELINE_LV0     ID      -         -	    save_response_index
	#Serial RECEIVELINE_LV0     BASE    -		  -	    0,0,0

	try:

		ID = TestData.getContent(line[2])
		SAVE_RESPONSE_INDEX = TestData.getContent(line[6])

		port = getPort(ID)

		rcv = port.readline().decode().replace("\n","")

		UI.addToLbox("Saving " + rcv + " @ " + SAVE_RESPONSE_INDEX)
		TestData.setContent(SAVE_RESPONSE_INDEX, rcv)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#RECEIVES BYTE ARRAY WITH PREDETERMINED LENGTH AND SAVES ITS CONTENTS
async def READBYTES_LV0(line, UI):

	#0      1                 2       4            5		6
	#Serial READBYTES_LV0     ID      -            NBYTES	save_response_index
	#Serial READBYTES_LV0     BASE    -			   5		0,0,0

	try:

		ID = TestData.getContent(line[2])
		NBYTES = int(TestData.getContent(line[5]))
		SAVE_RESPONSE_INDEX = TestData.getContent(line[6])

		port = getPort(ID)

		rcv = array.array('B', port.read(NBYTES))

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		UI.addToLbox("Saving " + byteArrayToString(rcv) + " @ " + SAVE_RESPONSE_INDEX)
		TestData.setContent(SAVE_RESPONSE_INDEX, byteArrayToString(rcv))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#RECEIVES BYTE ARRAY TERMINATED WITH 0x10 AND SAVES ITS CONTENTS
async def READBYTES_LT_LV0(line, UI):

	#0      1                    2       4         5		6
	#Serial READBYTES_LT_LV0     ID      -         -	    save_response_index
	#Serial READBYTES_LT_LV0     BASE    -			-	    0,0,0

	try:

		ID = TestData.getContent(line[2])
		SAVE_RESPONSE_INDEX = TestData.getContent(line[6])

		port = getPort(ID)

		rcv = array.array('B', port.readline())

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		UI.addToLbox("Saving " + byteArrayToString(rcv) + " @ " + SAVE_RESPONSE_INDEX)
		TestData.setContent(SAVE_RESPONSE_INDEX, byteArrayToString(rcv))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV1

#RECEIVE STRING TERMINATED WITH \n AND EVALUATES ITS CONTENTS
async def READLINE_LV1(line, UI):

	#0      1                2       4                        5		6
	#Serial READLINE_LV1     ID      TARGET_RECEIVE_STRING    -	    save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial READLINE_LV1     BASE    targetstring			   		    0,0,0;0,0,1
	#Serial READLINE_LV1     BASE    targetstring           		    0,0,0

	try:

		ID = TestData.getContent(line[2])
		TARGET_RECEIVE_STRING = TestData.getContent(line[4])
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)

		rcv = port.readline().decode().replace("\n","")

		if(TARGET_RECEIVE_STRING in rcv):

			saveResult("PASS", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#RECEIVES BYTE ARRAY WITH PREDETERMINED LENGTH AND EVALUATES ITS CONTENTS
async def READBYTES_LV1(line, UI):

	#0      1                 2       4                        5		6
	#Serial READBYTES_LV1     ID      TARGET_RECEIVE_ARRAY     NBYTES	save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial READBYTES_LV1     BASE    79,75,13,10			   5		0,0,0;0,0,1
	#Serial READBYTES_LV1     BASE    79,75,13,10              5		0,0,0

	try:

		ID = TestData.getContent(line[2])
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		NBYTES = int(TestData.getContent(line[5]))
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)

		rcv = array.array('B', port.read(NBYTES))

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

			saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#RECEIVES BYTE ARRAY TERMINATED WITH 0x10 AND EVALUATES ITS CONTENTS
async def READBYTES_LT_LV1(line, UI):

	#0      1                    2       4                        5		    6
	#Serial READBYTES_LT_LV1     ID      TARGET_RECEIVE_ARRAY     -	        save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial READBYTES_LT_LV1     BASE    79,75,13,10			  -			0,0,0;0,0,1
	#Serial READBYTES_LT_LV1     BASE    79,75,13,10              -			0,0,0

	try:

		ID = TestData.getContent(line[2])
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		rcv = array.array('B', port.readline())

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

			saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV2

#RECEIVES BYTE ARRAY WITH PREDETERMINED LENGTH AND EVALUATES ITS CONTENTS, HAS INBUILT RETRIES
async def READBYTES_LV2(line, UI):

	#0      1                 2       4                        5		6
	#Serial READBYTES_LV2     ID      TARGET_RECEIVE_ARRAY     NBYTES	save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial READBYTES_LV2     BASE    79,75,13,10			   5		0,0,0;0,0,1
	#Serial READBYTES_LV2     BASE    79,75,13,10              5		0,0,0

	try:

		ID = TestData.getContent(line[2])
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		EXTRA_INFO = TestData.getContent(line[5]).split(',')
		NBYTES = int(EXTRA_INFO[0])
		TRIES = int(EXTRA_INFO[1])
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		counter = 0

		while(counter < TRIES):

			counter = counter + 1

			rcv = array.array('B', port.read(NBYTES))

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:
				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

				saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
				return

			await asyncio.sleep(.2)

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV3

#RECEIVES BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND EVALUATES RESULT, HAS INBUILT RETRIES, UPDATES UI AND KILLS INDEX
async def READBYTES_LT_LV3(line, UI):

	#0      1                    2       4                        5		    						6
	#Serial READBYTES_LT_LV1     ID      TARGET_RECEIVE_ARRAY     TRIES,KILL_INDEX,TEST_NAME	    save_result_index
	#Serial READBYTES_LT_LV1     BASE    79,75,13,10			  5,0,UART							0,0,0

	try:

		ID = TestData.getContent(line[2])
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		EXTRA_INFO = TestData.getContent(line[5]).split(',')
		TRIES = int(EXTRA_INFO[0])
		KILL_INDEX = EXTRA_INFO[1]
		TEST_NAME = EXTRA_INFO[2]
		SAVE_RESULT_INDEX = TestData.getContent(line[6])

		port = getPort(ID)

		counter = 0
		rcv = None

		while(counter < TRIES):

			counter = counter + 1

			rcv = array.array('B', port.readline())

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:
				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

				grid_message = ['-']*11
				grid_message[0] = TEST_NAME
				grid_message[1] = str( int(KILL_INDEX) + 1 )
				grid_message[5] = byteArrayToString(rcv)
				grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
				grid_message[8] = "PASS"
				grid_message[10] = "PASS"
				updateGRID(KILL_INDEX, grid_message, UI)

				saveTestResult(byteArrayToString(rcv), "PASS", SAVE_RESULT_INDEX, TEST_NAME, UI)
				return

			else:

				grid_message = ['-']*11
				grid_message[0] = TEST_NAME
				grid_message[1] = str( int(KILL_INDEX) + 1 )
				grid_message[5] = byteArrayToString(rcv)
				grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
				grid_message[8] = "RETRY"
				grid_message[10] = "RETRY"
				updateGRID(KILL_INDEX, grid_message, UI)
				UI.addToLbox("Response did not match target :(")

		grid_message = ['-']*11
		grid_message[0] = TEST_NAME
		grid_message[1] = str( int(KILL_INDEX) + 1 )
		grid_message[5] = byteArrayToString(rcv)
		grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
		grid_message[8] = "FAIL"
		grid_message[10] = "FAIL"
		updateGRID(KILL_INDEX, grid_message, UI)

		saveTestResult(byteArrayToString(rcv), "FAIL", SAVE_RESULT_INDEX, TEST_NAME, UI)
		TestData.kill(KILL_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#***************************************************************************************************************************************

#**************************************************************EXCHANGE*****************************************************************

#LVS

#EXCHANGES STRING AND EVALUATES RECEIVED, IF DOESN'T MATCH, RAISE SYSTEM EXCEPTION TO ABORT TEST
async def EXCHANGELINE_LVS(line, UI):

	#0      1                2    3       4       5
	#Serial EXCHANGELINE_LVS ID   MESSAGE RECEIVE TRIES
	#Serial EXCHANGELINE_LVS BASE q/      y       5

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3]).replace("/n","\n")
		TARGET_MESSAGE = TestData.getContent(line[4])
		TRIES = int(TestData.getContent(line[5]))

		port = getPort(ID)
		flushBuffers(port)

		counter = 0
		while(counter < TRIES):

			counter = counter + 1

			UI.addToLbox("Sending " + MESSAGE.strip() + " at port " + ID)
			port.write(MESSAGE.encode())
			rcv = port.readline().decode().replace("\n","")

			if(TARGET_MESSAGE in rcv):

				UI.addToLbox("Received message " + rcv + " matches target")

				return

			else:

				UI.addToLbox("Received message " + rcv + " doesn't match target")

		UI.addToLbox("Counter timeout, raising EXCEPTION..")

		raise Exception("FAILED TO EXCHANGE MESSAGE: " + MESSAGE + " AT " + ID)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGES BYTES AND EVALUATES RECEIVED, IF DOESN'T MATCH, RAISE SYSTEM EXCEPTION TO ABORT TEST
async def EXCHANGEBYTES_LVS(line, UI):

	#0      1                 2       3               4                      5
	#Serial EXCHANGEBYTES_LVS ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   NBYTES,TRIES
	#Serial EXCHANGEBYTES_LVS BASE    79,75,13,10     79,75,13,10            5,5
	#Serial EXCHANGEBYTES_LVS BASE    79,75,13,10     79,75,13,10            5,5

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		EXTRA_INFO = TestData.getContent(line[5]).split(',')
		NBYTES = int(EXTRA_INFO[0])
		TRIES = int(EXTRA_INFO[1])

		port = getPort(ID)
		flushBuffers(port)

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		counter = 0
		while(counter < TRIES):

			counter = counter + 1

			UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

			port.write(bytearray(byte_array_write))
			rcv = array.array('B', port.read(NBYTES))

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:
				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY,UI)):

				UI.addToLbox("Received message " + byteArrayToString(rcv) + " matches target")
				return

			UI.addToLbox("Received message " + byteArrayToString(rcv) + " doesn't match target")

		UI.addToLbox("Counter timeout, raising EXCEPTION..")
		raise Exception("FAILED TO EXCHANGE MESSAGE: " + byteArrayToString(MESSAGE_ARRAY) + " AT " + ID)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV0

#EXCHANGE BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND SAVES IT
async def EXCHANGEBYTES_LT_LV0(line, UI):

	#0      1                    2       3               4                5                  6
	#Serial EXCHANGEBYTES_LT_LV0 ID      MESSAGE_ARRAY   -           	  -					 save_index
	#Serial EXCHANGEBYTES_LT_LV0 BASE    79,75,13,10     -                -					 0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		INDEX = TestData.getContent(line[6])

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		port.write(bytearray(byte_array_write))
		#rcv = array.array('B', port.readline())
		rcv = port.readline().decode().replace("\n","")

		UI.addToLbox("Received: " + rcv)

		TestData.setContent(line[6], rcv)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGE BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND SAVES IT
async def EXCHANGELINE_LT_LV0(line, UI):

	#0      1                    2       3               4                5                  6
	#Serial EXCHANGELINE_LT_LV0 ID      MESSAGE   		 -           	  -					 save_index
	#Serial EXCHANGELINE_LT_LV0 BASE    "d/n"    		 -                -					 0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3]).replace("/n","\n")
		INDEX = TestData.getContent(line[6])

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + MESSAGE.strip() + " on port " + ID + "..")

		port.write(MESSAGE.encode())

		rcv = port.readline().decode().replace("\n","")

		UI.addToLbox("Received: " + rcv)

		TestData.setContent(INDEX, rcv)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV1

#EXCHANGE STRING WITH \n TERMINATOR AND EVALUATES RESULT
async def EXCHANGELINE_LV1(line, UI):

	#0      1                  2       3               4                     5      6
	#Serial EXCHANGELINE_LV1  ID      MESSAGE         TARGET_MESSAGE         -      save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGELINE_LV1  BASE    SEND_MESSAGE    TARGET_MESSAGE         -      0,0,0;1,0,0
	#Serial EXCHANGELINE_LV1  BASE    SEND_MESSAGE    TARGET_MESSAGE         -      0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3]).replace("/n","\n")
		TARGET_MESSAGE = TestData.getContent(line[4])
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + MESSAGE + " on port " + ID + "..")

		port.write(MESSAGE.encode())
		rcv = port.readline().decode().replace("\n","")

		if(TARGET_MESSAGE in rcv):

			saveResult("PASS", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGE BYTE ARRAYS WITH PREDETERMINED LENGTH, AND EVALUATES RESULT
async def EXCHANGEBYTES_LV1(line, UI):

	#0      1                 2       3               4                      5                6
	#Serial EXCHANGEBYTES_LV1 ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   NBYTES           save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGEBYTES_LV1 BASE    79,75,13,10     79,75,13,10            5                0,0,0;1,0,0
	#Serial EXCHANGEBYTES_LV1 BASE    79,75,13,10     79,75,13,10            5                0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		NBYTES = int(TestData.getContent(line[5]))
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		port.write(bytearray(byte_array_write))
		rcv = array.array('B', port.read(NBYTES))

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

			saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGE BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND EVALUATES RESULT
async def EXCHANGEBYTES_LT_LV1(line, UI):

	#0      1                    2       3               4                      5                6
	#Serial EXCHANGEBYTES_LT_LV1 ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   -           	  save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGEBYTES_LT_LV1 BASE    79,75,13,10     79,75,13,10            -                0,0,0;1,0,0
	#Serial EXCHANGEBYTES_LT_LV1 BASE    79,75,13,10     79,75,13,10            -                0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		port.write(bytearray(byte_array_write))
		rcv = array.array('B', port.readline())

		rcv_array = []
		UI.addToLbox("Bytes received: " + str(rcv))
		for _byte in rcv:
			rcv_array.append(str(_byte))

		if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

			saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
			return

		UI.addToLbox("Response did not match target :(")
		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV2

#EXCHANGE STRING WITH \n TERMINATOR AND EVALUATES RESULT, HAS INBUILT RETRIES
async def EXCHANGELINE_LV2(line, UI):

	#0      1                 2       3               4                      5       6
	#Serial EXCHANGELINE_LV2  ID      MESSAGE         TARGET_MESSAGE         TRIES   save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGELINE_LV2  BASE    SEND_MESSAGE    TARGET_MESSAGE         5       0,0,0;1,0,0
	#Serial EXCHANGELINE_LV2  BASE    SEND_MESSAGE    TARGET_MESSAGE         5       0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE = TestData.getContent(line[3]).replace("/n","\n")
		TARGET_MESSAGE = TestData.getContent(line[4])
		TRIES = int(TestData.getContent(line[5]))
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)

		flushBuffers(port)

		UI.addToLbox("Writing " + MESSAGE + " on port " + ID + "..")

		counter = 0
		rcv = None
		while(counter < TRIES):

			counter = counter + 1

			port.write(MESSAGE.encode())
			rcv = port.readline().decode().replace("\n","")

			if(TARGET_MESSAGE in rcv):

				saveResult("PASS", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

				return

			else:

				UI.addToLbox("Response did not match target :(")

		saveResult("FAIL", rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGE BYTE ARRAYS WITH PREDETERMINED LENGTH, AND EVALUATES RESULT, HAS INBUILT RETRIES
async def EXCHANGEBYTES_LV2(line, UI):

	#0      1                 2       3               4                      5                      6
	#Serial EXCHANGEBYTES_LV2 ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   NBYTES,TRIES           save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGEBYTES_LV2 BASE    79,75,13,10     79,75,13,10            5,5                	0,0,0;1,0,0
	#Serial EXCHANGEBYTES_LV2 BASE    79,75,13,10     79,75,13,10            5,5              		0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		EXTRA_INFO = TestData.getContent(line[5]).split(',')
		NBYTES = int(EXTRA_INFO[0])
		TRIES = int(EXTRA_INFO[0])
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		rcv = None
		counter = 0

		while(counter < TRIES):

			counter = counter + 1

			UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

			port.write(bytearray(byte_array_write))
			rcv = array.array('B', port.read(NBYTES))

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:
				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

				saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
				return

			else:

				UI.addToLbox("Response did not match target :(")

		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#EXCHANGE BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND EVALUATES RESULT, HAS INBUILT RETRIES
async def EXCHANGEBYTES_LT_LV2(line, UI):

	#0      1                      2       3               4                      5       6
	#Serial EXCHANGEBYTES_LT_LV2   ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   TRIES   save_result_index(PASS/FAIL);save_response_index :: save_response_index is optional
	#Serial EXCHANGEBYTES_LT_LV2   BASE    79,75,13,10     79,75,13,10            5       0,0,0;1,0,0
	#Serial EXCHANGEBYTES_LT_LV2   BASE    79,75,13,10     79,75,13,10            5       0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		TRIES = int(TestData.getContent(line[5]))
		INDEXES = TestData.getContent(line[6]).split(';')
		if(len(INDEXES) == 2):

			SAVE_RESULT_INDEX = INDEXES[0]
			SAVE_RESPONSE_INDEX = INDEXES[1]

		elif(len(INDEXES) == 1):

			SAVE_RESULT_INDEX = INDEXES
			SAVE_RESPONSE_INDEX = None

		else:

			raise Exception("Invalid input parameters at line[6].")

		port = getPort(ID)
		flushBuffers(port)

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		counter = 0
		rcv = None
		while(counter < TRIES):

			counter = counter + 1

			UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

			port.write(bytearray(byte_array_write))
			rcv = array.array('B', port.readline())

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:

				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

				saveResult("PASS", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)
				return

			else:

				UI.addToLbox("Response did not match target :(")

		saveResult("FAIL", byteArrayToString(rcv), UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#LV3

#EXCHANGE BYTE ARRAYS WITH LINE TERMINATOR 0x10, AND EVALUATES RESULT, HAS INBUILT RETRIES, UPDATES UI AND KILLS INDEX
async def EXCHANGEBYTES_LT_LV3(line, UI):

	#0      1                      2       3               4                      5       						6
	#Serial EXCHANGEBYTES_LT_LV2   ID      MESSAGE_ARRAY   TARGET_RECEIVE_ARRAY   TRIES,KILL_INDEX,TEST_NAME   	save_result_index
	#Serial EXCHANGEBYTES_LT_LV2   BASE    79,75,13,10     79,75,13,10            5,0,UART						0,0,0

	try:

		ID = TestData.getContent(line[2])
		MESSAGE_ARRAY = TestData.getContent(line[3]).split(',')
		TARGET_RECEIVE_ARRAY = TestData.getContent(line[4]).split(',')
		EXTRA_INFO = TestData.getContent(line[5]).split(',')
		TRIES = int(EXTRA_INFO[0])
		KILL_INDEX = EXTRA_INFO[1]
		TEST_NAME = EXTRA_INFO[2]
		SAVE_RESULT_INDEX = TestData.getContent(line[6])

		port = getPort(ID)
		flushBuffers(port)

		byte_array_write = []
		for byte_str in MESSAGE_ARRAY:
			byte_array_write.append(int(byte_str))

		counter = 0
		rcv = None
		while(counter < TRIES):

			counter = counter + 1

			UI.addToLbox("Writing " + line[3] + " on port " + ID + "..")

			port.write(bytearray(byte_array_write))
			rcv = array.array('B', port.readline())

			rcv_array = []
			UI.addToLbox("Bytes received: " + str(rcv))
			for _byte in rcv:

				rcv_array.append(str(_byte))

			if(compareArrays(rcv_array, TARGET_RECEIVE_ARRAY, UI)):

				grid_message = ['-']*11
				grid_message[0] = TEST_NAME
				grid_message[1] = str( int(KILL_INDEX) + 1 )
				grid_message[5] = byteArrayToString(rcv)
				grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
				grid_message[8] = "PASS"
				grid_message[10] = "PASS"
				updateGRID(KILL_INDEX, grid_message, UI)

				saveTestResult(byteArrayToString(rcv), "PASS", SAVE_RESULT_INDEX, TEST_NAME, UI)

				return

			else:

				grid_message = ['-']*11
				grid_message[0] = TEST_NAME
				grid_message[1] = str( int(KILL_INDEX) + 1 )
				grid_message[5] = byteArrayToString(rcv)
				grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
				grid_message[8] = "RETRY"
				grid_message[10] = "RETRY"
				UI.addToLbox("Grid Message: " + str(grid_message))
				updateGRID(KILL_INDEX, grid_message, UI)

				UI.addToLbox("Response did not match target :(")

		grid_message = ['-']*11
		grid_message[0] = TEST_NAME
		grid_message[1] = str( int(KILL_INDEX) + 1 )
		grid_message[5] = byteArrayToString(rcv)
		grid_message[6] = byteArrayToString(TARGET_RECEIVE_ARRAY)
		grid_message[8] = "FAIL"
		grid_message[10] = "FAIL"
		updateGRID(KILL_INDEX, grid_message, UI)

		saveTestResult(byteArrayToString(rcv), "FAIL", SAVE_RESULT_INDEX, TEST_NAME, UI)
		TestData.kill(KILL_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#***************************************************************************************************************************************

#**********************************************************VIKING SCANNER***************************************************************

async def READVKING(line, UI):

	#0		1			2			3			4		5
	#Serial	READVKING	ID			SAVE_INDEX	TRIES	KILL_INDEX
	#Serial	READVKING	SCANNER		0,0,0		5		0

	try:

		prefix_temp = bytes([0x7E, 0x01, 0x30, 0x30, 0x30, 0x30, 0x23])
		trigger = bytes([0x53, 0x43, 0x4E, 0x54, 0x52, 0x47, 0x31])
		sufix = bytes([0x3B, 0x03])
		
		message = prefix_temp + trigger + sufix
		ID = TestData.getContent(line[2])
		SAVE_INDEX = TestData.getContent(line[3])
		TRIES = int(TestData.getContent(line[4]))
		KILL_INDEX = TestData.getContent(line[5])

		port = getPort(ID)
		flushBuffers(port)

		counter = 0
		while(counter < TRIES):
			counter = counter + 1

			UI.addToLbox("Writing " + message.decode('utf-8', errors='ignore') + " on port " + ID + "..")
			port.write(message)
			
			response = port.readline()
			if len(response) >= 17:
				extracted_data = response[17:]
				barcode = extracted_data.decode('utf-8').strip()
				UI.addToLbox(f"Extracted response data starting from position 17: {barcode}")
				TestData.setContent(SAVE_INDEX, barcode)
				return
			else:
				UI.addToLbox("Response is too short to extract data from position 17.")

		TestData.kill(KILL_INDEX)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#HELPERS

def getPort(ID):

	global portlist

	for port in portlist:

		if(port is None):

			continue

		if(port["ID"] == ID):

			return port["Port"]

	raise Exception("Port " + ID + " not found!")

def compareArrays(array1, array2, UI):

	try:

		if(len(array1) != len(array2)):

			UI.addToLbox("Arrays dimensions do not match!")
			UI.addToLbox("Array1: " + str(len(array1)))
			UI.addToLbox("Array2: " + str(len(array2)))
			return False

		for i in range(len(array1)):

			if(array1[i] == array2[i]):

				continue

			else:

				return False

		return True

	except Exception as e:

		UI.addToLbox(str(e))
		return False

def byteArrayToString(array):

	_string = ""
	first_element = True
	for element in array:

		if(first_element):
			_string = _string + str(element)
		else:
			_string = _string + ' ' + str(element)
		first_element = False

	return _string

def saveResult(result, rcv, UI, SAVE_RESULT_INDEX, SAVE_RESPONSE_INDEX):

	if(result == "PASS"):

		UI.addToLbox("Saving PASS @ " + SAVE_RESULT_INDEX)
		TestData.setContent(SAVE_RESULT_INDEX, "PASS")

		if(SAVE_RESPONSE_INDEX is not None):

			try:

				UI.addToLbox("Saving " + rcv + " @ " + SAVE_RESPONSE_INDEX)
				TestData.setContent(SAVE_RESPONSE_INDEX, rcv)

			except Exception as e:

				UI.addToLbox("Exception:: " + str(e))
				UI.addToLbox("Saving " + "None" + " @ " + SAVE_RESPONSE_INDEX)
				TestData.setContent(SAVE_RESPONSE_INDEX, "None")

	elif(result == "FAIL"):

		UI.addToLbox("Saving FAIL @ " + SAVE_RESULT_INDEX)
		TestData.setContent(SAVE_RESULT_INDEX, "FAIL")

		if(SAVE_RESPONSE_INDEX is not None):

			try:

				UI.addToLbox("Saving " + rcv + " @ " + SAVE_RESPONSE_INDEX)
				TestData.setContent(SAVE_RESPONSE_INDEX, rcv)

			except Exception as e:

				UI.addToLbox("Exception:: " + str(e))
				UI.addToLbox("Saving " + "None" + " @ " + SAVE_RESPONSE_INDEX)
				TestData.setContent(SAVE_RESPONSE_INDEX, "None")

def saveTestResult(result, validation, index, test_name, UI):

	try:

		triple_index = getTripleIndex(index)

		if(validation == "PASS"):

			TestData.setContent(triple_index[0], result)
			TestData.setContent(triple_index[1], "PASS")
			TestData.setContent(triple_index[2], test_name)
			return

		else:

			TestData.setContent(triple_index[0], result)
			TestData.setContent(triple_index[1], "FAIL")
			TestData.setContent(triple_index[2], test_name)

	except Exception as e:

		UI.addToLbox(str(e))
		TestData.setContent(triple_index[0], result)
		TestData.setContent(triple_index[1], "FAIL")
		TestData.setContent(triple_index[2], test_name)

def getTripleIndex(base_index):

	values = base_index.split(',')

	triple_index = []

	triple_index.append(base_index)
	triple_index.append(values[0]+','+str(int(values[1])+1)+','+values[2])
	triple_index.append(values[0]+','+str(int(values[1])+2)+','+values[2])

	return triple_index

def flushBuffers(ser):

	ser.flushInput()
	ser.flushOutput()

def openPort(portname, baudrate, _timeout):

	ser = serial.Serial(

	    port = str(portname),
	    baudrate = int(baudrate),
	    timeout = float(_timeout),
	    bytesize = serial.EIGHTBITS, #number of bits per bytes
	    parity = serial.PARITY_NONE, #set parity check: no parity
	    stopbits = serial.STOPBITS_ONE #number of stop bits
	)

	return ser

def updateGRID(grid_index, grid_message, UI):

	if(grid_index == "0"):

		UIManager.SYNCGRID1(["UI","GRID1","Add","var",grid_message,"-","-","UI_EX","-","-","-"],UI)

	elif(grid_index == "1"):

		UIManager.SYNCGRID2(["UI","GRID2","Add","var",grid_message,"-","-","UI_EX","-","-","-"],UI)



#end
