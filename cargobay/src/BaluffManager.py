from mvIMPACT import acquire
from mvIMPACT.Common import exampleHelper
import numpy as np
import ctypes
import cv2
import sys

import TestData

#BaluffManager
#Allows creating Balluff (mvIMPACT Acquire) camera objects to capture images.
#Mirrors the API of CameraManager so it can be consumed the same way from the flow layer.

camera_objs = [None]*20

# The DeviceManager MUST outlive every Device/FunctionInterface handle we hand out.
# When the last DeviceManager instance is destroyed, mvIMPACT unloads the driver stack
# and invalidates all open pDev/fi handles, causing a native crash on the next driver
# call (e.g. fi.imageRequestSingle() in CAPTURE). Keep one alive at module scope.
_devMgr = acquire.DeviceManager()

#Open a single camera
def OPEN(line, UI):

    global camera_objs

    #0      1     2
    #Camera OPEN  serial_or_substring
    #Camera OPEN  GX002467

    #Opens a Balluff device whose serial contains the given substring and stores it at camera_objs[i]["obj"],
    #where i is the device index reported by mvIMPACT's DeviceManager.
    #Also stores its serial at camera_objs[i]["ID"].

    try:

        target_id = TestData.getContent(line[2])

        devMgr = _devMgr
        deviceCount = devMgr.deviceCount()

        for i in range(deviceCount):

            pDev = devMgr.getDevice(i)
            serial = pDev.serial.read()

            if target_id in serial:

                if not pDev.isOpen:
                    pDev.open()

                camera_objs[i] = _build_obj(pDev, serial)
                UI.addToLbox("Camera object found, stored at camera_objs[" + str(i) + "]")
                UI.addToLbox("ID: " + str(serial))

    except Exception as e:

            raise Exception(line[7] + "::" + str(e))

#Open all existing cameras
def OPENALL(line, UI):

    global camera_objs

    #0      1
    #Camera OPENALL

    #Opens all Balluff devices and stores them at camera_objs[i]["obj"],
    #where i is the device index reported by mvIMPACT's DeviceManager.
    #Also stores their serials at camera_objs[i]["ID"].

    try:

        devMgr = _devMgr
        deviceCount = devMgr.deviceCount()

        for i in range(deviceCount):

            pDev = devMgr.getDevice(i)
            serial = pDev.serial.read()

            if not pDev.isOpen:
                pDev.open()

            camera_objs[i] = _build_obj(pDev, serial)
            UI.addToLbox("Camera object found, stored at camera_objs[" + str(i) + "]")
            UI.addToLbox("ID: " + str(serial))

    except Exception as e:

            raise Exception(line[7] + "::" + str(e))

#Set the properties of a camera
def SETPROPS(line, UI):

    #0      1        2                      3                       4               5                     6
    #Camera SETPROPS serial_substring       BUFFERSIZE,WIDTH,HEIGHT AUTOFOCUS,FOCUS AUTOEXPOSURE,EXPOSURE HUE,SATURATION,BRIGHTNESS,TEMPERATURE
    #Camera SETPROPS GX002467               4,1296,972              0,0             0,20000               0,100,0,0

    #BlueFOX mapping notes:
    #  BUFFERSIZE      -> number of image requests pre-queued at CAPTURE time
    #  WIDTH, HEIGHT   -> AOI width/height; 0 means leave at sensor default
    #  AUTOFOCUS,FOCUS -> not applicable on BlueFOX (fixed-focus); silently ignored
    #  AUTOEXPOSURE    -> cameraSettings.autoExposeControl (0=off, 1=on)
    #  EXPOSURE        -> cameraSettings.expose_us (microseconds, NOT the OpenCV log-scale range)
    #  HUE             -> not applicable; silently ignored
    #  SATURATION      -> imageProcessing.setSaturation(value) (typical range 0..200, 100 = neutral)
    #  BRIGHTNESS      -> cameraSettings.gain_dB
    #  TEMPERATURE     -> non-zero triggers a one-shot WB calibration on the next captured frame

    try:

        DIMS = TestData.getContent(line[3]).split(',')
        FOCUSINFO = TestData.getContent(line[4]).split(',')
        EXPOSUREINFO = TestData.getContent(line[5]).split(',')
        COLORINFO = TestData.getContent(line[6]).split(',')

        BUFFERSIZE = int(DIMS[0])
        WIDTH = int(DIMS[1])
        HEIGHT = int(DIMS[2])

        AUTOFOCUS = int(FOCUSINFO[0])
        FOCUS = int(FOCUSINFO[1])

        AUTOEXPOSURE = int(EXPOSUREINFO[0])
        EXPOSURE = int(EXPOSUREINFO[1])

        HUE = int(COLORINFO[0])
        SATURATION = int(COLORINFO[1])
        BRIGHTNESS = int(COLORINFO[2])
        TEMPERATURE = int(COLORINFO[3])

        camobj = get_camera(line[2])

        camobj["buffersize"] = max(1, BUFFERSIZE)

        cs = camobj["cameraSettings"]
        ip = camobj["imageProcessing"]

        # Match the original ContinuousCapture defaults: 2x2 binning is what the existing flow uses.
        exampleHelper.conditionalSetProperty(cs.binningMode, acquire.cbmBinningHV)

        # WIDTH,HEIGHT are the desired OUTPUT resolution, NOT a raw-sensor AOI. The AOI is
        # measured in full-sensor pixels and is independent of binning, so to get a W x H
        # output under 2x2 binning the sensor AOI must be (W*2) x (H*2). The AOI is also
        # sticky between captures, so we always reset it to the full sensor first and then,
        # only if a size was requested, apply a CENTERED AOI of the right size.
        # Result: 1296,972 -> full field of view at 1296x972 (not a top-left quarter crop);
        # a smaller value -> a centered crop at exactly that output size.
        BINX = 2  # cbmBinningHV -> 2x2
        BINY = 2

        try:
            maxW = cs.aoiWidth.getMaxValue()
            maxH = cs.aoiHeight.getMaxValue()

            # Reset to the full sensor (clear any crop left by a previous SETPROPS).
            exampleHelper.conditionalSetProperty(cs.aoiStartX, 0)
            exampleHelper.conditionalSetProperty(cs.aoiStartY, 0)
            exampleHelper.conditionalSetProperty(cs.aoiWidth, maxW)
            exampleHelper.conditionalSetProperty(cs.aoiHeight, maxH)

            if WIDTH > 0 and HEIGHT > 0:
                aoiW = min(WIDTH * BINX, maxW)
                aoiH = min(HEIGHT * BINY, maxH)
                # Center, aligned to the binning factor to satisfy the AOI position step.
                startX = ((maxW - aoiW) // 2) // BINX * BINX
                startY = ((maxH - aoiH) // 2) // BINY * BINY
                # Size first (start is 0 so it always fits), then offset to center.
                exampleHelper.conditionalSetProperty(cs.aoiWidth, aoiW)
                exampleHelper.conditionalSetProperty(cs.aoiHeight, aoiH)
                exampleHelper.conditionalSetProperty(cs.aoiStartX, startX)
                exampleHelper.conditionalSetProperty(cs.aoiStartY, startY)
                UI.addToLbox("AOI " + str(aoiW) + "x" + str(aoiH) + " @ (" + str(startX) + "," +
                             str(startY) + ") -> output " + str(aoiW // BINX) + "x" + str(aoiH // BINY))
        except Exception as aoi_e:
            UI.addToLbox("AOI setup skipped: " + str(aoi_e))

        exampleHelper.conditionalSetProperty(cs.autoExposeControl, AUTOEXPOSURE)
        if AUTOEXPOSURE == 0 and EXPOSURE > 0:
            exampleHelper.conditionalSetProperty(cs.expose_us, EXPOSURE)

        # BRIGHTNESS -> gain in dB (clamp to sensor's valid range to avoid throwing here)
        try:
            gain_min = cs.gain_dB.getMinValue()
            gain_max = cs.gain_dB.getMaxValue()
            cs.gain_dB.write(max(gain_min, min(gain_max, float(BRIGHTNESS))))
        except Exception:
            pass

        try:
            ip.setSaturation(float(SATURATION))
        except Exception:
            pass

        if TEMPERATURE != 0:
            exampleHelper.conditionalSetProperty(ip.whiteBalanceCalibration, acquire.wbcmNextFrame)

        if AUTOFOCUS != 0 or FOCUS != 0:
            UI.addToLbox("Focus settings ignored (BlueFOX has no controllable focus)")
        if HUE != 0:
            UI.addToLbox("HUE setting ignored (not supported on BlueFOX)")

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Calibrate white balance ONCE and lock the gains -- call from the <Config> section.
def CALIBRATEWB(line, UI):

    #0      1           2                3                      4
    #Camera CALIBRATEWB serial_substring CALIB_EXPOSURE_us(opt) WARMUP(opt)
    #Camera CALIBRATEWB UB101256         20000                  -
    #Camera CALIBRATEWB UB101256         -                      -    (defaults: 20000us, warmup 5)

    #Run this ONCE, at config time, with a properly-exposed white/gray reference (or a well-lit
    #neutral scene) in view. It performs a next-frame WB calibration and leaves the resulting
    #per-channel gains locked in the User1 parameter set. CAPTURE then reuses those gains on every
    #frame (including the dark inspection frames) instead of recalibrating: gray-world auto-WB on a
    #mostly-black frame computes gains of ~1.0 (no correction), which is what caused the green cast.
    #
    #The config normally runs at a very low exposure, which is far too dark to measure white
    #balance on. WB gains are exposure-independent ratios, so this method temporarily raises the
    #exposure to CALIB_EXPOSURE_us (default 20000) just for the calibration frames, then restores
    #whatever exposure/auto-exposure state was already configured.
    #
    #SYNC on purpose -- the <Config> section runs its calls synchronously (not awaited), like
    #OPEN/OPENALL/SETPROPS.

    try:

        camobj = get_camera(line[2])
        pDev = camobj["pDev"]
        fi = camobj["fi"]
        ip = camobj["imageProcessing"]
        cs = camobj["cameraSettings"]

        CALIB_EXPOSURE = 20000
        if len(line) > 3 and str(line[3]) not in ('-', ''):
            CALIB_EXPOSURE = int(TestData.getContent(line[3]))
        WARMUP = 5
        if len(line) > 4 and str(line[4]) not in ('-', ''):
            WARMUP = max(2, int(TestData.getContent(line[4])))

        # Remember the config's exposure state so we can put it back afterwards.
        prev_autoexp = cs.autoExposeControl.read()
        prev_expose = cs.expose_us.read()

        # Debayer + apply WB from the User1 set.
        exampleHelper.conditionalSetProperty(ip.colorProcessing, acquire.cpmAuto)
        exampleHelper.conditionalSetProperty(ip.whiteBalance, acquire.wbpUser1)

        # Raise exposure to a level bright enough to measure white balance on (clamped to range).
        exampleHelper.conditionalSetProperty(cs.autoExposeControl, 0)
        try:
            emin = cs.expose_us.getMinValue()
            emax = cs.expose_us.getMaxValue()
            CALIB_EXPOSURE = max(emin, min(emax, CALIB_EXPOSURE))
        except Exception:
            pass
        cs.expose_us.write(CALIB_EXPOSURE)
        UI.addToLbox("WB calibrating at " + str(CALIB_EXPOSURE) + "us exposure")

        # Calibrate on the next frame.
        exampleHelper.conditionalSetProperty(ip.whiteBalanceCalibration, acquire.wbcmNextFrame)

        for _ in range(4):
            if fi.imageRequestSingle() != acquire.DMR_NO_ERROR:
                break

        exampleHelper.manuallyStartAcquisitionIfNeeded(pDev, fi)

        try:
            for _ in range(WARMUP):
                requestNr = fi.imageRequestWaitFor(10000)
                if not fi.isRequestNrValid(requestNr):
                    raise Exception("imageRequestWaitFor failed (" + str(requestNr) + ", " +
                                    acquire.ImpactAcquireException.getErrorCodeAsString(requestNr) + ")")
                pRequest = fi.getRequest(requestNr)
                pRequest.unlock()
                fi.imageRequestSingle()
        finally:
            exampleHelper.manuallyStopAcquisitionIfNeeded(pDev, fi)
            fi.imageRequestReset(0, 0)
            # Freeze gains (stop recalibration) and restore the config's original exposure state.
            exampleHelper.conditionalSetProperty(ip.whiteBalanceCalibration, acquire.wbcmOff)
            exampleHelper.conditionalSetProperty(cs.autoExposeControl, prev_autoexp)
            if prev_autoexp == 0:
                cs.expose_us.write(prev_expose)

        wbs = ip.getWBUserSetting(0)
        gains = (wbs.redGain.read(), wbs.greenGain.read(), wbs.blueGain.read())
        camobj["wb_gains"] = gains
        UI.addToLbox("WB calibrated & locked: R=%.2f G=%.2f B=%.2f" % gains)

        # gains ~1.0 mean the reference frame was too dark/neutral to measure -> calibration was a no-op.
        if abs(gains[0] - 1.0) < 0.02 and abs(gains[2] - 1.0) < 0.02:
            UI.addToLbox("WARNING: WB gains ~1.0 -- reference too dark; calibrate on a brighter white target")

    except Exception as e:

        # <Config> rows carry no exception label (line[7] is blank), so don't depend on it --
        # fall back to a fixed tag. Still honour a real label if one is ever passed from a flow row.
        label = str(line[7]) if len(line) > 7 and str(line[7]).strip() not in ('', '-') else "CALIBRATEWB"
        raise Exception(label + "::" + str(e))

#Set only the shutter speed (exposure time) of a camera
async def SETEXPOSURE(line, UI):

    #0      1           2                 3
    #Camera SETEXPOSURE serial_substring  EXPOSURE_us
    #Camera SETEXPOSURE UB101256          100

    #Sets the manual exposure time (shutter speed) in microseconds on a single camera,
    #without touching any other property. Auto-exposure is turned OFF first, otherwise the
    #driver ignores expose_us. The value is clamped to the sensor's supported range so an
    #out-of-range request is reported and applied at the nearest limit instead of being
    #silently dropped by conditionalSetProperty.

    try:

        EXPOSURE = int(TestData.getContent(line[3]))

        camobj = get_camera(line[2])
        cs = camobj["cameraSettings"]

        exampleHelper.conditionalSetProperty(cs.autoExposeControl, 0)

        try:
            emin = cs.expose_us.getMinValue()
            emax = cs.expose_us.getMaxValue()
            if EXPOSURE < emin or EXPOSURE > emax:
                UI.addToLbox("Exposure " + str(EXPOSURE) + "us out of range [" +
                             str(emin) + ", " + str(emax) + "], clamping")
                EXPOSURE = max(emin, min(emax, EXPOSURE))
        except Exception:
            pass

        cs.expose_us.write(EXPOSURE)
        UI.addToLbox("Exposure set to " + str(EXPOSURE) + "us")

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Capture the image of a camera
async def CAPTURE(line, UI):

    #0      1       2                 3                  4
    #Camera CAPTURE serial_substring  dir_to_save_image  save_index_to_save_img
    #Camera CAPTURE UB101256          testimage.png      -
    #Camera CAPTURE UB101256          -                  0,0,1

    try:

        dir_to_save_image = None
        img_save_index = None

        camobj = get_camera(line[2])

        pDev = camobj["pDev"]
        fi = camobj["fi"]
        ip = camobj["imageProcessing"]
        buffersize = camobj.get("buffersize", 4)

        # White balance is calibrated ONCE via CALIBRATEWB; the gains are locked in the User1
        # parameter set. Here we only make sure the pipeline actually applies them (Auto colour
        # processing + User1 as the active set). We deliberately do NOT recalibrate per frame:
        # gray-world calibration on a mostly-black inspection scene computes gains of ~1.0 (no
        # correction), which is exactly what left the green cast. Run 'Camera CALIBRATEWB
        # <serial>' once against a well-lit white/gray reference to set the gains for the session.
        exampleHelper.conditionalSetProperty(ip.colorProcessing, acquire.cpmAuto)
        exampleHelper.conditionalSetProperty(ip.whiteBalance, acquire.wbpUser1)

        # Pre-queue requests
        for _ in range(buffersize):
            if fi.imageRequestSingle() != acquire.DMR_NO_ERROR:
                break

        exampleHelper.manuallyStartAcquisitionIfNeeded(pDev, fi)


        # Capture a few warmup frames so any pending wbcmNextFrame calibration settles,
        # then keep the last frame for output. Mirrors the double-read in CameraManager.CAPTURE.
        WARMUP = 3
        pPrev = None
        pKept = None
        try:
            for i in range(WARMUP):

                requestNr = fi.imageRequestWaitFor(10000)
                if not fi.isRequestNrValid(requestNr):
                    raise Exception("imageRequestWaitFor failed (" + str(requestNr) + ", " +
                                    acquire.ImpactAcquireException.getErrorCodeAsString(requestNr) + ")")
                              
                pRequest = fi.getRequest(requestNr)
                if not pRequest.isOK:
                    pRequest.unlock()
                    fi.imageRequestSingle()
                    continue

                if i == WARMUP - 1:
                    pKept = pRequest
                else:
                    if pPrev is not None:
                        pPrev.unlock()
                    pPrev = pRequest
                    fi.imageRequestSingle()

            if pKept is None:
                raise Exception("No valid frame captured")

            frame = _request_to_bgr(pKept)

            # Surface the calibration result so it is obvious whether WB actually fired.
            # Neutral 1.00/1.00/1.00 gains mean the calibration did NOT run (green cast would
            # remain); calibrated scenes here settle around R~2 / G=1 / B~2.
            try:
                wbs = ip.getWBUserSetting(0)
                UI.addToLbox("WB gains R=%.2f G=%.2f B=%.2f" %
                             (wbs.redGain.read(), wbs.greenGain.read(), wbs.blueGain.read()))
            except Exception:
                pass

            if line[3] != '-':
                dir_to_save_image = TestData.getContent(line[3])
                UI.addToLbox("Saving image at " + dir_to_save_image)
                # Prefer the SDK saver (handles all pixel formats via FreeImage); fall back to cv2.
                result = pKept.getImageBufferDesc().save(dir_to_save_image, acquire.iffAuto)
                if result != acquire.DMR_NO_ERROR:
                    cv2.imwrite(dir_to_save_image, frame)

            print("9")

            if line[4] != '-':
                img_save_index = TestData.getContent(line[4])
                UI.addToLbox("Saving image at " + img_save_index)
                TestData.setContentNS(img_save_index, frame)

        finally:
            if pPrev is not None and pPrev is not pKept:
                pPrev.unlock()
            if pKept is not None:
                pKept.unlock()
            exampleHelper.manuallyStopAcquisitionIfNeeded(pDev, fi)
            # Drain anything still queued so the next CAPTURE starts clean.
            fi.imageRequestReset(0, 0)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Helpers

#Input: serial_substring unique to each camera element
#Output: Corresponding camera object dict {pDev, fi, cameraSettings, imageProcessing, statistics, buffersize}
#Returns the camera object that matches the serial_substring
def get_camera(serial_substring):

    global camera_objs

    for obj in camera_objs:

        if obj is None:

            continue

        if serial_substring in obj["ID"]:

            return obj["obj"]

    opened = [obj["ID"] for obj in camera_objs if obj is not None]
    raise Exception("Camera not found for serial '" + str(serial_substring) +
                    "'. Opened cameras: " + (str(opened) if opened else "none (was OPEN/OPENALL called?)"))

#Builds the per-device handle bundle stored in camera_objs[i]
def _build_obj(pDev, serial):

    return {
        "ID": serial,
        "obj": {
            "pDev": pDev,
            "fi": acquire.FunctionInterface(pDev),
            "cameraSettings": acquire.CameraSettingsBlueFOX(pDev),
            "imageProcessing": acquire.ImageProcessing(pDev),
            "statistics": acquire.Statistics(pDev),
            "buffersize": 4,
        }
    }

#Converts a captured Request into a BGR numpy array compatible with cv2/ImageProcessManager.
def _request_to_bgr(pRequest):

    # Reconstruct straight from the buffer geometry the driver reports, NOT from
    # channelCount. Packed color formats (e.g. RGBx888Packed) carry a padding byte,
    # so bytesPerPixel (4) != channelCount (3); linePitch also absorbs any row padding.
    width = pRequest.imageWidth.read()
    height = pRequest.imageHeight.read()
    channels = pRequest.imageChannelCount.read()
    bitDepth = pRequest.imageChannelBitDepth.read()
    size = pRequest.imageSize.read()
    linePitch = pRequest.imageLinePitch.read()          # bytes per row, incl. padding
    bytesPerPixel = pRequest.imageBytesPerPixel.read()  # bytes per pixel, incl. padding

    dtype = np.uint16 if bitDepth > 8 else np.uint8
    itemsize = np.dtype(dtype).itemsize
    slots = max(1, bytesPerPixel // itemsize)           # value-slots per pixel (channels + padding)
    rowSlots = linePitch // itemsize                    # value-slots per row (incl. row padding)

    cbuf = (ctypes.c_ubyte * size).from_address(int(pRequest.imageData.read()))
    arr = np.frombuffer(cbuf, dtype=dtype)
    arr = arr[:height * rowSlots].reshape((height, rowSlots))
    arr = arr[:, :width * slots].reshape((height, width, slots))

    if slots == 1:
        return arr[:, :, 0].copy()                      # mono

    # mvIMPACT's packed color formats (RGBx888Packed / BGRx888Packed / BGR888Packed) are
    # little-endian DWORDs, so the in-memory slot order is B, G, R[, x] -- already OpenCV's
    # BGR order. Taking the first 3 slots reproduces getImageBufferDesc().save() EXACTLY
    # (verified against the SDK saver). Only true 3-byte RGB888Packed is stored R,G,B.
    pf = pRequest.imagePixelFormat.readS()
    bgr = arr[:, :, :3]
    if pf == "RGB888Packed":
        bgr = bgr[:, :, ::-1]
    return bgr.copy()
    return arr.copy()

#USAGE EXAMPLE

#OPEN(['Camera', 'OPEN', 'GX002467','-','-','-','-','CAM_EX'], UI)
#OPENALL(['Camera', 'OPENALL','-','-','-','-','-','CAM_EX'], UI)
#SETPROPS(['Camera', 'SETPROPS', 'GX002467', '4,0,0', '0,0', '0,20000', '0,100,0,1', 'CAM_EX'], UI)
#CALIBRATEWB(['Camera', 'CALIBRATEWB', 'GX002467', '20000', '-', '-', '-', 'CAM_EX'], UI)   # <-- once, in <Config>
#SETEXPOSURE(['Camera', 'SETEXPOSURE', 'GX002467', '100', '-', '-', '-', 'CAM_EX'], UI)
#CAPTURE(['Camera', 'CAPTURE', 'GX002467', 'temp.png', '-', '-', '-', 'CAM_EX'], UI)
