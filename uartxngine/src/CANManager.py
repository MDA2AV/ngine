import argparse
import shutil
import TestData

from canlib import canlib, Frame

bitrates = {
    '1M': canlib.Bitrate.BITRATE_1M,
    '500K': canlib.Bitrate.BITRATE_500K,
    '250K': canlib.Bitrate.BITRATE_250K,
    '125K': canlib.Bitrate.BITRATE_125K,
    '100K': canlib.Bitrate.BITRATE_100K,
    '62K': canlib.Bitrate.BITRATE_62K,
    '50K': canlib.Bitrate.BITRATE_50K,
    '83K': canlib.Bitrate.BITRATE_83K,
    '10K': canlib.Bitrate.BITRATE_10K,
}

#Write UDS message
async def UDSWRITE(line, UI):

    #0   1        2                                                3        4        5    6
    #CAN UDSWRITE channel,bitrate,ticktime,width,height,timeout    SendID   SendDATA -    l,c,p (save result string)

    CAN_info = TestData.getContent(line[2])
    CAN_info = CAN_info.split(',')

    timeout = float(CAN_info[5])

    ID_info = TestData.getContent(line[3])

    sendData = TestData.getContent(line[4])
    sendData = sendData.split(',')
    data_array = []

    for databyte in sendData:

        data_array.append(int(databyte))

    #number_bytes_to_receive = int(TestData.getContent(line[5]).split(',')[0])
    #number_frames_till_timeout = int(TestData.getContent(line[5]).split(',')[1])

    try:

        ch = canlib.openChannel(int(CAN_info[0]), bitrate=bitrates[CAN_info[1]])
        ch.setBusOutputControl(canlib.canDRIVER_NORMAL)
        ch.busOn()

        width, height = shutil.get_terminal_size((int(CAN_info[3]), int(CAN_info[4])))

        ch.write(Frame(id_ = int(ID_info), data=data_array))
        UI.addToLbox("Writing on CAN, ID:" + str(ID_info) + ", DATA: " + TestData.getContent(line[4]))

        byte_counter = 0
        frame_counter = 0

        ch.busOff()
        ch.close()

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))


#Exchange UDS message
async def UDSEXCHANGE(line, UI):

    #0   1           2                                              3                  4          5                                        6
    #CAN UDSEXCHANGE channel,bitrate,ticktime,width,height,timeout  SendID,ReceiveID   SendDATA   nbytes_to_receive,n_frames_till_timeout  0,0,0 (save result string)

    CAN_info = TestData.getContent(line[2])
    CAN_info = CAN_info.split(',')

    timeout = float(CAN_info[5])

    ID_info = TestData.getContent(line[3])
    ID_info = ID_info.split(',')

    sendData = TestData.getContent(line[4])
    sendData = sendData.split(',')
    data_array = []

    for databyte in sendData:

        data_array.append(int(databyte))

    number_bytes_to_receive = int(TestData.getContent(line[5]).split(',')[0])
    number_frames_till_timeout = int(TestData.getContent(line[5]).split(',')[1])

    try:

        ch = canlib.openChannel(int(CAN_info[0]), bitrate=bitrates[CAN_info[1]])
        ch.setBusOutputControl(canlib.canDRIVER_NORMAL)
        ch.busOn()

        width, height = shutil.get_terminal_size((int(CAN_info[3]), int(CAN_info[4])))

        ch.write(Frame(id_ = int(ID_info[0]), data=data_array))
        UI.addToLbox("Writing on CAN, ID:" + str(ID_info[0]) + ", DATA: " + TestData.getContent(line[4]))

        byte_counter = 0
        frame_counter = 0

        rcv = []

        while byte_counter < number_bytes_to_receive:

            frame = ch.read(timeout=int(timeout * 1000))
            UI.addToLbox("Received from CAN: " + str(frame))
            frame_counter += 1

            if(frame_counter > number_frames_till_timeout):

                UI.addToLbox("Number of frames received exceeded timeout.")
                break

            if(frame.id == int(ID_info[1])):

                for fram in frame.data:

                    byte_counter += 1
                    rcv.append(fram)

                ch.write(Frame(id_ = int(ID_info[0]), data=[48,0,0,0,0,0,0,0]))

        received_string = ""
        for received_byte in rcv:

            received_string += str(received_byte)

        TestData.setContent(line[6], received_string)
        UI.addToLbox(line[6] + " = " + received_string)

        ch.busOff()
        ch.close()

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

async def TRACEMSG(line, UI):

    #0   1        2                                               3           4               5                      6
    #CAN TRACEMSG channel,bitrate,ticktime,width,height,timeout   ReceiveID   targetMessage   n_frames_till_timeout  0,0,0(save index)

    CAN_info = line[2]
    CAN_info = CAN_info.split(',')

    timeout = float(CAN_info[5])

    ID_info = TestData.getContent(line[3])

    targetMessage = TestData.getContent(line[4])

    number_frames_till_timeout = int(line[5])

    rcv = []

    try:

        ch = canlib.openChannel(int(CAN_info[0]), bitrate=bitrates[CAN_info[1]])
        ch.setBusOutputControl(canlib.canDRIVER_NORMAL)
        ch.busOn()

        width, height = shutil.get_terminal_size((int(CAN_info[3]), int(CAN_info[4])))

        frame_counter = 0

        while frame_counter < number_frames_till_timeout:

            frame = ch.read(timeout=int(timeout * 1000))
            frame_counter += 1

            if(frame.id == int(ID_info)):

                received_frame = ""

                for fram in frame.data:

                    received_frame += str(fram) + " "

                if(received_frame == targetMessage):

                    UI.addToLbox("Messaged traced sucessfully: " + received_frame)
                    TestData.setContent(line[6], "O.K.")
                    UI.addToLbox(line[6] + " = " + "O.K.")

                    break

        if(frame_counter >= number_frames_till_timeout):

            UI.addToLbox("Number of frames received exceeded timeout.")
            TestData.setContent(line[6], "FAIL")
            UI.addToLbox(line[6] + " = " + "FAIL")

        ch.busOff()
        ch.close()

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))
