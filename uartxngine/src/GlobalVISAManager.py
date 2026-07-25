#Improved VISA library 13/3/2023

import TestData
import pyvisa
import asyncio
import UIManager
import threading

VISA_objs = [None]*20

#Open a VISA resource
def OPENALL(line, UI):

    #0    1       2       3
	#VISA OPENALL timeout number_devices

	#Open all VISA resources and stores them at visa_objs[]

    global VISA_objs

    VISA_objs = [None]*20 #RESET objs

    try:

        number_devices = int(TestData.getContent(line[3]))

        UI.addToLbox("Opening ALL VISA resources..")
        UI.addToLbox("Listing all found resources:")

        rm = pyvisa.ResourceManager()
        UI.addToLbox(rm.list_resources())

        VISA_resources = rm.list_resources()

        UI.addToLbox("Opening..")

        device_counter = 0

        for i in range(len(VISA_resources)):

            if(len(VISA_resources[i]) < 40):

                continue

            VISA_objs[i] = {"ID": VISA_resources[i], "RESOURCE": rm.open_resource(VISA_resources[i])}
            VISA_objs[i]["RESOURCE"].timeout = int(TestData.getContent(line[2]))

            UI.addToLbox(VISA_objs[i]["ID"] + " opened @ " + str(i) + " timeout: " + str(TestData.getContent(line[2])))
            UI.addToLbox("Querying IDN..")
            UI.addToLbox(VISA_objs[i]["RESOURCE"].query("*IDN?"))

            device_counter = device_counter + 1

        if(device_counter != number_devices):

            raise Exception("Number of devices found does not match target!")

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

async def WRITE(line,UI):

    #0    1     2     3          "7"
	#VISA WRITE ID    message    "exception_label"

	#Write a message on a VISA resource stored at data.

    try:

        ID = TestData.getContent(line[2])
        message = TestData.getContent(line[3])

        UI.addToLbox("Writing on VISA resource (" + ID + "): " + message + " ..")

        getResource(ID).write(message)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Write and Read from a VISA resource
async def EXCHANGE(line,UI):

	#0    1        2     3       4            "7"
	#VISA EXCHANGE ID    message l,c,p        "exception_label"

	#Exchanges messages with a VISA resource, done by query. Writes a message and gets a response, then stores the response at data.

    try:

        ID = TestData.getContent(line[2])
        message = TestData.getContent(line[3])

        UI.addToLbox("Querying on VISA resource (" + ID + "): " + message)

        response = getResource(ID).query(message)

        UI.addToLbox("Query response: " + response + ":: saving @" + line[4] + "..")
        TestData.setContent(TestData.getContent(line[4]), response)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

async def MEASURE(line,UI):

	#0    1                2        3        5
	#VISA MEASURE          ID       query    save_index
	#index: 0,0,0

    try:

        ID = TestData.getContent(line[2])
        query = TestData.getContent(line[3])
        save_index = TestData.getContent(line[5])

        rcv = getResource(ID).query(query)

        TestData.setContent(save_index, rcv)

        UI.addToLbox(save_index + " = " + rcv)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

async def MEASURE_FEVAL(line,UI):

	#0    1                2        3        4                        5                6
	#VISA MEASURE_EVAL     ID       query    lower_lim,upper_lim      save_index       TRIES,kill_index,TEST_NAME,TRIES
	#index: 0,0,0

    try:

        ID = TestData.getContent(line[2])
        query = TestData.getContent(line[3])

        limits = TestData.getContent(line[4]).split(',')
        lower_limit = float(limits[0])
        upper_limit = float(limits[1])

        save_index = TestData.getContent(line[5])

        extra_info = TestData.getContent(line[6]).split(',')
        TRIES = int(extra_info[0])
        kill_index = extra_info[1]
        TEST_NAME = extra_info[2]

        counter = 0
        while(counter < TRIES):

            counter = counter + 1

            rcv = float(getResource(ID).query(query))

            if( (lower_limit<=rcv) and (rcv<=upper_limit) ):

                UI.addToLbox("Received PASS value: " +  str(rcv))

                saveTestResult(str(rcv), "PASS", save_index, TEST_NAME, UI)
                grid_message = ['-']*11
                grid_message[0] = TEST_NAME
                grid_message[1] = str( int(kill_index) + 1 )
                grid_message[2] = limits[0]
                grid_message[4] = limits[1]
                grid_message[5] = str(rcv)
                grid_message[8] = "PASS"
                grid_message[10] = "PASS"
                updateGRID(kill_index, grid_message, UI)

                return

            else:

                UI.addToLbox("Received RETRY value: " +  str(rcv))

                grid_message = ['-']*11
                grid_message[0] = TEST_NAME
                grid_message[1] = str( int(kill_index) + 1 )
                grid_message[2] = limits[0]
                grid_message[4] = limits[1]
                grid_message[5] = str(rcv)
                grid_message[8] = "RETRY"
                grid_message[10] = "RETRY"
                updateGRID(kill_index, grid_message, UI)

        UI.addToLbox("Timeout, last received: " +  str(rcv))

        grid_message = ['-']*11
        grid_message[0] = TEST_NAME
        grid_message[1] = str( int(kill_index) + 1 )
        grid_message[2] = limits[0]
        grid_message[4] = limits[1]
        grid_message[5] = str(rcv)
        grid_message[8] = "FAIL"
        grid_message[10] = "FAIL"
        updateGRID(kill_index, grid_message, UI)

        saveTestResult(str(rcv), "FAIL", save_index, TEST_NAME, UI)

        TestData.kill(kill_index)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

async def MASS_MEASURE(line,UI):

	#0    1                2        3        5
	#VISA MASS_MEASURE     ID       query    indexes
	#indexes: 0,0,0;0,0,1;0,0,2 ...

    try:

        ID = TestData.getContent(line[2])
        query = TestData.getContent(line[3])
        indexes = TestData.getContent(line[5]).split(';')

        rcv = getResource(ID).query(query)
        values = rcv.split(',')
        i = 0
        for value in values:

            TestData.setContent(indexes[i], value)
            UI.addToLbox(indexes[i] + " = " + value)
            i += 1

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Helpers

def getResource(ID):

    global VISA_objs

    for i in range(len(VISA_objs)):

        if(VISA_objs[i] is None):

            continue

        if(ID in VISA_objs[i]["ID"]):

            return VISA_objs[i]["RESOURCE"]

    raise Exception("VISA object not found for ID: " + str(ID))

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

def updateGRID(grid_index, grid_message, UI):

	if(grid_index == "0"):

		UIManager.SYNCGRID1(["UI","GRID1","Add","var",grid_message,"-","-","UI_EX","-","-","-"],UI)

	elif(grid_index == "1"):

		UIManager.SYNCGRID2(["UI","GRID2","Add","var",grid_message,"-","-","UI_EX","-","-","-"],UI)

def getTripleIndex(base_index):

	values = base_index.split(',')

	triple_index = []

	triple_index.append(base_index)
	triple_index.append(values[0]+','+str(int(values[1])+1)+','+values[2])
	triple_index.append(values[0]+','+str(int(values[1])+2)+','+values[2])

	return triple_index
