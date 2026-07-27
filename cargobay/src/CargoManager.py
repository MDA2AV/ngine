import TestData
import UIManager
import tkinter as tk
import xml.etree.ElementTree as ET
from datetime import datetime

NPasses = 0

async def VALIDATE_DET(line, UI):

    # Kill PCBAs that are not detected

    # Cargo     VALIDATE_DET    value_read

    try:

        input = TestData.getContent(line[2])
        value = to_int(input) - 16  # Result should be 0-15 (4-bit hex digit)

        if value < 0 or value > 15:
            print(f"Error: {value} is out of range (0-15)")
            raise Exception("Invalid detection")

        for bit in range(4):
            if not (value & (1 << bit)):
                UI.addToLbox("Killing " + str(bit))
                TestData.kill(str(bit))

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))
    

async def VALIDATE(line,UI):

    global NPasses

    # Variables Definition

    barcode_UUT1 = TestData.getData("2,0,20")
    barcode_UUT2 = TestData.getData("3,0,20")

    UUT1_VALS = [
        "0,1,0",
        "0,1,1", 
        "0,1,2", "1,1,2", "2,1,2", "3,1,2", "4,1,2", "5,1,2",
        "0,1,4", "1,1,4", "2,1,4", "3,1,4", "4,1,4"
    ]

    UUT2_VALS = [
        "1,1,0",
        "1,1,1",
        "0,1,3", "1,1,3", "2,1,3", "3,1,3", "4,1,3", "5,1,3",
        "0,1,5", "1,1,5", "2,1,5", "3,1,5", "4,1,5"
    ]

    UUT1_TARGET = 13
    UUT2_TARGET = 13

    UUT1_PASSES = 0
    UUT2_PASSES = 0

    UUT1_RESULT = False
    UUT2_RESULT = False

    print("CHK1")

    #Validate UUT1
    for ref1 in UUT1_VALS:
        try:
            val = TestData.getData(ref1)
            if(not(val is None)):
                print("val: " + val)
        except Exception as e:
            print("001: " + str(e))
            pass
        
        parts = ref1.split(",")
        parts[1] = "2"
        idref1 = ",".join(parts)
        valId = TestData.getData(idref1)
        
        if(val == "PASS"):
            UUT1_PASSES += 1

    TestData.setContent("39,0,29", UUT1_PASSES)

    print("CHK2")

    #Validate UUT2
    for ref2 in UUT2_VALS:
        try:
            val = TestData.getData(ref2)
            if(not(val is None)):
                print("val: " + val)
        except Exception as e:
            print("001: " + str(e))
            pass

        parts = ref2.split(",")
        parts[1] = "2"
        idref2 = ",".join(parts)
        valId = TestData.getData(idref2)

        if(val == "PASS"):
            UUT2_PASSES += 1

    print("CHK3")

    TestData.setContent("39,1,29", UUT2_PASSES)

    if(UUT1_PASSES == UUT1_TARGET):
        UUT1_RESULT = True

    if(UUT2_PASSES == UUT2_TARGET):
        UUT2_RESULT = True
    
    if(UUT1_RESULT and UUT2_RESULT):
        UI.frames[0].status_label.configure(text = "1: PASS 2: PASS")
        UI.frames[0].status_label.configure(fg_color = "#62AF75")
        UI.frames[0].progressbar.configure(progress_color = "#62AF75")
        NPasses += 2
        #uut1result.text = "PASS"

    if(UUT1_RESULT and not UUT2_RESULT):
        UI.frames[0].status_label.configure(text = "1: PASS 2: FAIL")
        UI.frames[0].status_label.configure(fg_color = "#c2a24d")
        UI.frames[0].progressbar.configure(progress_color = "#c2a24d")
        NPasses += 1
        #uut1result.text = "PASS"

    if(not UUT1_RESULT and UUT2_RESULT):
        UI.frames[0].status_label.configure(text = "1: FAIL 2: PASS")
        UI.frames[0].status_label.configure(fg_color = "#c2a24d")
        UI.frames[0].progressbar.configure(progress_color = "#c2a24d")
        NPasses += 1
        #uut1result.text = "FAIL"

    if(not UUT1_RESULT and not UUT2_RESULT):
        UI.frames[0].status_label.configure(text = "1: FAIL 2: FAIL")
        UI.frames[0].status_label.configure(fg_color = "#9e342d")
        UI.frames[0].progressbar.configure(progress_color = "#9e342d")
        #uut1result.text = "FAIL"

    UI.frames[0].sum_label.configure(text = str(NPasses))

    print("CHK4")

    # Save result XML

    current_date = datetime.now()
    end_date_string = current_date.strftime("%Y%m%d_%H%M%S")
    start_date_string = TestData.getContent("*38,0,29")

    if(not (barcode_UUT1 is None)):

        uut1FileName = barcode_UUT1 + "_" + end_date_string + ".xml"
        uut1xml = ET.Element("LOG_XML")
        filename = ET.SubElement(uut1xml, "filename").text = uut1FileName
        serialNumber1 = ET.SubElement(uut1xml, "serialnumber").text = barcode_UUT1
        supplier = ET.SubElement(uut1xml, "supplier").text = "UARTRONICA"
        starttime = ET.SubElement(uut1xml, "starttime").text = start_date_string
        endtime = ET.SubElement(uut1xml, "endtime").text = end_date_string
        if(UUT1_RESULT):
            uut1result = ET.SubElement(uut1xml, "result").text = "PASS"
        else:
            uut1result = ET.SubElement(uut1xml, "result").text = "FAIL"
        tasksuut1 = ET.SubElement(uut1xml, "tasks")

        for ref1 in UUT1_VALS:

            val = TestData.getData(ref1)

            parts = ref1.split(",")
            parts[1] = "2"
            idref1 = ",".join(parts)
            valId = TestData.getData(idref1)

            if(valId is None):
                print("valId is None")
                continue
            else:
                print("valId: " + str(valId))

            task = ET.SubElement(tasksuut1, "task", {"name": valId})

            if(val == "PASS"):
                ET.SubElement(task, "result").text = "PASS"
            else:
                if(not(val is None)):
                    ET.SubElement(task, "result").text = "FAIL"
                else:
                    ET.SubElement(task, "result").text = "-"

    print("CHK5")

    if(not (barcode_UUT2 is None)):

        uut2FileName = barcode_UUT2 + "_" + end_date_string + ".xml"
        uut2xml = ET.Element("LOG_XML")
        filename = ET.SubElement(uut2xml, "filename").text = uut2FileName
        serialNumber2 = ET.SubElement(uut2xml, "serialnumber").text = barcode_UUT2
        supplier = ET.SubElement(uut2xml, "supplier").text = "UARTRONICA"
        starttime = ET.SubElement(uut2xml, "starttime").text = start_date_string
        endtime = ET.SubElement(uut2xml, "endtime").text = end_date_string
        if(UUT2_RESULT):
            uut2result = ET.SubElement(uut2xml, "result").text = "PASS"
        else:
            uut2result = ET.SubElement(uut2xml, "result").text = "FAIL"
        tasksuut2 = ET.SubElement(uut2xml, "tasks")

        for ref2 in UUT2_VALS:

            val = TestData.getData(ref2)

            parts = ref2.split(",")
            parts[1] = "2"
            idref2 = ",".join(parts)
            valId = TestData.getData(idref2)

            if(valId is None):
                print("valId is None")
                continue
            else:
                print("valId: " + str(valId))

            task = ET.SubElement(tasksuut2, "task", {"name": valId})

            if(val == "PASS"):
                ET.SubElement(task, "result").text = "PASS"
            else:
                if(not(val is None)):
                    ET.SubElement(task, "result").text = "FAIL"
                else:
                    ET.SubElement(task, "result").text = "-"

    print("CHK6")

    # Create the ElementTree object and write to file
    if(not(barcode_UUT1 is None)):
        tree = ET.ElementTree(uut1xml)
        tree.write(TestData.getData("4,0,23")+"/"+uut1FileName, encoding="utf-8", xml_declaration=True)
        tree.write(TestData.getData("6,0,23")+"/"+uut1FileName, encoding="utf-8", xml_declaration=True)
    if(not(barcode_UUT2 is None)):
        tree = ET.ElementTree(uut2xml)
        tree.write(TestData.getData("4,0,23")+"/"+uut2FileName, encoding="utf-8", xml_declaration=True)
        tree.write(TestData.getData("6,0,23")+"/"+uut2FileName, encoding="utf-8", xml_declaration=True)

    print("CHK7")


async def VALIDATE_BCODE(line, UI):

    #0      1                   2               3                   4                   5                       6
    #1121   VALIDATE_BCODE      *bcode_index    result_index        target_length       target_eng_level        kill_index
    #1121   VALIDATE_BCODE      *0,0,20         0,0,0               24                  R02                     0
    
    try:

        bcode = TestData.getContent(line[2])
        result_index = getTripleIndex(TestData.getContent(line[3]))
        target_length = int(TestData.getContent(line[4]))
        target_eng_level = TestData.getContent(line[5])
        kill_index = TestData.getContent(line[6])

        if(len(bcode) != target_length):
            TestData.setContent(result_index[0], bcode)
            TestData.setContent(result_index[1], "FAIL")
            TestData.setContent(result_index[2], "Bcode")

            grid_message = "BCODE Length"+";"+str(int(kill_index)+1)+";"+"-"+";"+str(target_length)+";"+"-"+";"+str(len(bcode))+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.kill(kill_index)

            return


        eng_level = bcode[:3]

        UI.addToLbox("Barcode: " + str(bcode))
        UI.addToLbox("Eng level: " + str(eng_level))
        if(eng_level != target_eng_level):
            TestData.setContent(result_index[0], bcode)
            TestData.setContent(result_index[1], "FAIL")
            TestData.setContent(result_index[2], "Bcode")

            grid_message = "BCODE Eng Level"+";"+str(int(kill_index)+1)+";"+"-"+";"+target_eng_level+";"+"-"+";"+eng_level+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.kill(kill_index)

            return
        
        TestData.setContent(result_index[0], bcode)
        TestData.setContent(result_index[1], "PASS")
        TestData.setContent(result_index[2], "Bcode")

        grid_message = "BCODE"+";"+str(int(kill_index)+1)+";"+"-"+";-"+";"+"-"+";"+bcode+";-"+";-"+";PASS"+";-"+";PASS"
        add2GRID(grid_message, kill_index, UI)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))
    



#Helpers

def to_int(s):
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return int(s, 16)
    except ValueError:
        raise ValueError(f"Cannot convert {s!r} to int")

def add2GRID(grid_message, kill_index, UI):

    if(kill_index == '0'):
        UI.addToLbox("Adding " + grid_message)
        UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

    elif(kill_index == '1'):

        UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

def getTripleIndex(base_index):

	values = base_index.split(',')

	triple_index = []

	triple_index.append(base_index)
	triple_index.append(values[0]+','+str(int(values[1])+1)+','+values[2])
	triple_index.append(values[0]+','+str(int(values[1])+2)+','+values[2])

	return triple_index