from pygrabber.dshow_graph import FilterGraph
import cv2
import sys

from camgrabber.dshow_structures import *
from camgrabber.dshow_ids import *
from camgrabber.win_api_extra import *

from comtypes.persist import IPropertyBag
from comtypes import *
from ctypes import *


camera_objs = [None]*20

#Open a single camera
def OPEN():

    global camera_objs

    #0      1     2
    #Camera OPEN  \\\\?\\usb#vid_0c45&pid_6366&mi_00#7&183af011&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global

    #Opens a camera object and stores it at camera_objs[i]["obj"], i depends on the camera index attributed by windows.
    #Also stores its moniker at camera_objs[i]["ID"]

    try:
        print("OPEN")
        target_id = 'vid_0c45&pid_6366'
        category_clsid = DeviceCategories.CLSID_VideoInputDeviceCategory
        system_device_enum = client.CreateObject(clsids.CLSID_SystemDeviceEnum, interface=ICreateDevEnum)
        filter_enumerator = system_device_enum.CreateClassEnumerator(GUID(category_clsid), dwFlags=0)
        moniker, count = filter_enumerator.Next(1)
        result = []

        while count > 0:
            result.append(get_filter_name(moniker))
            moniker, count = filter_enumerator.Next(1)
            print(moniker)

        for i in range(len(result)):
            print(result[i])
            if(target_id in result[i]):
                camera_objs[i] = {"ID": target_id, "obj": cv2.VideoCapture(i, cv2.CAP_DSHOW)}
                print("Camera object found, stored at camera_objs[" + str(i) + "]")
                print("ID: " + str(target_id))

    except Exception as e:

            print(e)

#Set the properties of a camera
def SETPROPS():

    #0      1        2                      3                       4               5                     6
    #Camera SETPROPS vid_pid_identifier     BUFFERSIZE,WIDTH,HEIGHT AUTOFOCUS,FOCUS AUTOEXPOSURE,EXPOSURE HUE,SATURATION,BRIGHTNESS,TEMPERATURE
    #Camera SETPROPS vid_0c45&pid_6366      1,1920,1080             0,300           0,5                   50,50,50,50

    #Arducam Properties range
    #FOCUS 1-1023
    #EXPOSURE 1-10
    #HUE
    #SATURATION
    #BRIGHTNESS
    #TEMPERATURE

    try:

        BUFFERSIZE = 1
        WIDTH = 1024
        HEIGHT = 768

        AUTOFOCUS = 0
        FOCUS = 300

        AUTOEXPOSURE = 0
        EXPOSURE = -7

        HUE = 100
        SATURATION = 100
        BRIGHTNESS = 100
        TEMPERATURE = 100

        camobj = get_camera('vid_0c45&pid_6366')

        camobj.set(cv2.CAP_PROP_BUFFERSIZE,BUFFERSIZE)
        camobj.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        camobj.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        camobj.set(cv2.CAP_PROP_FOCUS, FOCUS)
        camobj.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE)
        camobj.set(cv2.CAP_PROP_HUE, HUE)
        camobj.set(cv2.CAP_PROP_SATURATION, SATURATION)
        camobj.set(cv2.CAP_PROP_BRIGHTNESS, BRIGHTNESS)
        camobj.set(cv2.CAP_PROP_WB_TEMPERATURE, TEMPERATURE)
        camobj.set(cv2.CAP_PROP_AUTO_WB, 0)
        camobj.set(cv2.CAP_PROP_AUTOFOCUS, AUTOFOCUS)
        camobj.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTOEXPOSURE)

        count = 0
        while True:

            camobj.set(cv2.CAP_PROP_FOCUS, FOCUS)

            count = count + 1

            ret, frame = camobj.read()
            if(count == 10):
                break

        camobj.set(cv2.CAP_PROP_AUTOFOCUS, AUTOFOCUS)

    except Exception as e:

        print(e)

#Capture the image of a camera
def CAPTURE():

    #0      1       2                  3                  4
    #Camera CAPTURE vid_pid_identifier dir_to_save_image save_index_to_save_img
    #Camera CAPTURE vid_0c45&pid_6366  testimage.png     -
    #Camera CAPTURE vid_0c45&pid_6366  -                 0,0,1

    try:

        dir_to_save_image = None
        img_save_index = None

        camobj = get_camera('vid_0c45&pid_6366')

        ret,frame = camobj.read()
        ret,frame = camobj.read()

        dir_to_save_image = 'C:\\Users\\Admin.ONTPC12\\Desktop\\Captures\\capture.jpg'
        print("Saving image at " + dir_to_save_image)
        cv2.imwrite(dir_to_save_image, frame)


    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Helpers

#Input: vid_pid_identifier unique to each camera element
#Output: Corresponding camera object
#Returns the camera object that matches the vid_pid_identifier
def get_camera(vid_pid_identifier):

    global camera_objs

    for obj in camera_objs:

        if obj is None:

            continue

        if vid_pid_identifier in obj["ID"]:

            return obj["obj"]

def get_filter_name(arg):

    if type(arg) == POINTER(IMoniker):

        property_bag = arg.BindToStorage(0, 0, IPropertyBag._iid_).QueryInterface(IPropertyBag)
        return property_bag.Read("DevicePath", pErrorLog=None)

    elif type(arg) == POINTER(qedit.IBaseFilter):

        filter_info = arg.QueryFilterInfo()
        return wstring_at(filter_info.achName)

    else:

        return Nones


OPEN()
SETPROPS()
CAPTURE()