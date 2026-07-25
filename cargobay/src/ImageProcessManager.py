import cv2
import numpy as np
import os
import datetime
import TestData
import UIManager

#ImageProcessManager
#ImageProcess
#Impro

#Proccesses existing images

# --- DEBUG: dump the search-window crops produced by the EVALCONT/EVALCONTN position filter ---
# Set DEBUG_SAVE_CROPS = False to turn off. One PNG is written per EVALCONT/EVALCONTN call, into
# DEBUG_CROP_DIR, named with the current date/time down to the second.
DEBUG_SAVE_CROPS = True
DEBUG_CROP_DIR = r"C:\Users\Admin.ONTPC12\Desktop\crgo"

_last_contour_frame = None      # source frame the most recent contour set was extracted from
_debug_crop_counter = 0

def _set_contour_frame(frame):
    #Remember the image a *2CONT step derived its contours from, so the EVALCONT/EVALCONTN
    #position filter can crop real pixels for debugging.
    global _last_contour_frame
    _last_contour_frame = frame

def _save_debug_crop(frame, cx, cy, tol, in_window_contours):
    #Save the position-filter search window (cx +/- tol) of `frame`, with any in-window contours
    #outlined in green and the target centre marked in red. The filename is timestamped to the
    #second, with the centre coords + a counter so several crops in the same second don't collide.
    #Wrapped so debug saving can never break a running test.
    global _debug_crop_counter
    if not DEBUG_SAVE_CROPS or frame is None:
        return
    try:
        h = frame.shape[0]
        w = frame.shape[1]
        x0 = max(0, cx - tol)
        y0 = max(0, cy - tol)
        x1 = min(w, cx + tol)
        y1 = min(h, cy + tol)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return
        crop = crop.copy()
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        for cnt in in_window_contours:
            shifted = (cnt - np.array([x0, y0], dtype=np.int32)).astype(np.int32)
            cv2.drawContours(crop, [shifted], -1, (0, 255, 0), 2)
        cv2.drawMarker(crop, (cx - x0, cy - y0), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        _debug_crop_counter += 1
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = "crop_" + ts + "_" + str(cx) + "x" + str(cy) + "_" + ("%03d" % _debug_crop_counter) + ".png"
        os.makedirs(DEBUG_CROP_DIR, exist_ok=True)
        cv2.imwrite(os.path.join(DEBUG_CROP_DIR, fname), crop)
    except Exception:
        pass  # debug saving must never break a test

def _log_contours(contours, UI):
    #Debug: log the centre, size (area) and radius of every significant contour just found.
    #Contours below the MIN_CONTOUR_PIXELS noise floor are counted but not listed, so the log
    #stays readable (a thresholded frame can produce hundreds of 1-pixel specks).
    if contours is None:
        contours = []
    logged = 0
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < MIN_CONTOUR_PIXELS:
            continue
        M = cv2.moments(cnt)
        if M['m00'] == 0:
            continue
        _cx = int(M['m10'] / M['m00'])
        _cy = int(M['m01'] / M['m00'])
        (_, _), radius = cv2.minEnclosingCircle(cnt)
        UI.addToLbox("  contour #" + str(i) + " center=(" + str(_cx) + "," + str(_cy) +
                     ") area=" + str(int(area)) + "px radius=" + str(round(radius, 1)) + "px")
        logged += 1
    UI.addToLbox("Contours: " + str(len(contours)) + " total, " + str(logged) + " >= " +
                 str(MIN_CONTOUR_PIXELS) + "px (" + str(len(contours) - logged) + " noise skipped)")

#Convert RGB image to gray scale
async def RGB2GRAY(line, UI):

    #0            1        2       3          4      5
    #ImageProcess RGB2GRAY *l,c,p  -          l,c,p  -
    #ImageProcess RGB2GRAY *l,c,p  -          -      save_dir
    #ImageProcess RGB2GRAY -       image_dir  -      save_dir
    #ImageProcess RGB2GRAY -       image_dir  l,c,p  -

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        saveImage(line[4], line[5], gray_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Convert BGR image to gray scale
async def BGR2GRAY(line, UI):

    #0            1        2       3          4      5
    #ImageProcess BGR2GRAY *l,c,p  -          l,c,p  -
    #ImageProcess BGR2GRAY *l,c,p  -          -      save_dir
    #ImageProcess BGR2GRAY -       image_dir  -      save_dir
    #ImageProcess BGR2GRAY -       image_dir  l,c,p  -

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        saveImage(line[4], line[5], gray_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Apply Binary filter to a gray scale image
async def GRAY2BIN(line, UI):

    #0            1            2       3          4      5         6
    #ImageProcess GRAY2BIN     *l,c,p  -          l,c,p  -         threshold_lvl
    #ImageProcess GRAY2BIN     *l,c,p  -          -      save_dir  threshold_lvl
    #ImageProcess GRAY2BIN     -       image_dir  -      save_dir  threshold_lvl
    #ImageProcess GRAY2BIN     -       image_dir  l,c,p  -         threshold_lvl

    try:

        gray_frame = getImage(line[2], TestData.getContent(line[3]), UI)

        threshold_lvl = int(TestData.getContent(line[6]))

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        saveImage(line[4], line[5], binary_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Convert RGB image to gray scale and then apply a binary filter on it
async def RGB2BIN(line, UI):

    #0            1            2       3          4      5         6
    #ImageProcess RGB2BIN      *l,c,p  -          l,c,p  -         threshold_lvl
    #ImageProcess RGB2BIN      *l,c,p  -          -      save_dir  threshold_lvl
    #ImageProcess RGB2BIN      -       image_dir  -      save_dir  threshold_lvl
    #ImageProcess RGB2BIN      -       image_dir  l,c,p  -         threshold_lvl

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        threshold_lvl = int(TestData.getContent(line[6]))

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        saveImage(line[4], line[5], binary_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Convert BGR image to gray scale and then apply a binary filter on it
async def BGR2BIN(line, UI):

    #0            1            2       3          4      5         6
    #ImageProcess BGR2BIN      *l,c,p  -          l,c,p  -         threshold_lvl
    #ImageProcess BGR2BIN      *l,c,p  -          -      save_dir  threshold_lvl
    #ImageProcess BGR2BIN      -       image_dir  -      save_dir  threshold_lvl
    #ImageProcess BGR2BIN      -       image_dir  l,c,p  -         threshold_lvl

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        threshold_lvl = int(TestData.getContent(line[6]))

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        saveImage(line[4], line[5], binary_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Get the contours of a binary image
async def BIN2CONT(line,UI):

    #0            1            2       3          4
    #ImageProcess BIN2CONT     *l,c,p  -          l,c,p
    #ImageProcess BIN2CONT     -       image_dir  l,c,p

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        contours, hierarchy= cv2.findContours(image=frame, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        TestData.setContentNS(line[4], contours)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Get the contours of a gray scale image
async def GRAY2CONT(line,UI):

    #0            1            2       3           4
    #ImageProcess GRAY2CONT     *l,c,p  -          l,c,p
    #ImageProcess GRAY2CONT     -       image_dir  l,c,p

    try:

        gray_frame = getImage(line[2], TestData.getContent(line[3]), UI)

        threshold_lvl = int(TestData.getContent(line[6]))

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        contours, hierarchy= cv2.findContours(image=frame, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        TestData.setContentNS(line[4], contours)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Get the contours of a BGR image
async def BGR2CONT(line,UI):

    #0            1            2       3          4      5   6
    #ImageProcess BGR2CONT     *l,c,p  -          l,c,p  -   threshold_lvl
    #ImageProcess BGR2CONT     -       image_dir  l,c,p  -   threshold_lvl

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)
        _set_contour_frame(frame)   # remember source for EVALCONT/EVALCONTN debug crops

        threshold_lvl = int(TestData.getContent(line[6]))

        UI.addToLbox("Applying gray filter..")

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        UI.addToLbox("Setting Threshold level to " + str(threshold_lvl))

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        if(line[5] != '-'):

            cv2.imwrite(TestData.getContent(line[5]), binary_frame)

        contours, hierarchy= cv2.findContours(image=binary_frame, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        TestData.setContentNS(line[4], contours)

        _log_contours(contours, UI)   # debug: log each contour's centre / area / radius

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Get the contours of a RGB image
async def RGB2CONT(line,UI):

    #0            1            2       3          4      5   6
    #ImageProcess RGB2CONT     *l,c,p  -          l,c,p  -   threshold_lvl
    #ImageProcess RGB2CONT     -       image_dir  l,c,p  -   threshold_lvl

    try:

        frame = getImage(line[2], TestData.getContent(line[3]), UI)

        threshold_lvl = int(TestData.getContent(line[6]))

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        ret,binary_frame = cv2.threshold(gray_frame,threshold_lvl,255,cv2.THRESH_BINARY)

        contours, hierarchy= cv2.findContours(image=binary_frame, mode=cv2.RETR_TREE, method=cv2.CHAIN_APPROX_NONE)

        TestData.setContentNS(line[4], contours)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#High level function :: Measures the pixel size of a contour in a determinted position cx,cy
async def MEASCONT(line,UI):

    #0            1        2        3                   4                     5           6
    #ImageProcess MEASCONT *l,c,p   cx,cy,tol           write_result_index    -           -

    try:

        contour_info = TestData.getContent(line[3]).split(',')

        contours = TestData.getContent(line[2])
        cx = int(contour_info[0])
        cy = int(contour_info[1])
        pixel_tol = int(contour_info[2])

        write_result_index = TestData.getContent(line[4]).split(';')

        min_cx = cx - pixel_tol
        min_cy = cy - pixal_tol

        if(min_cx < 0):

            min_cx = 0

        if(min_cy < 0):

            min_cy = 0

        max_cx = cx + pixel_tol
        max_cy = cy + pixel_tol

        contour_found = False
        contour_area_valid = False

        for contour in contours:

            M = cv2.moments(contour)

            _cx = int(M['m10']/M['m00'])
            _cy = int(M['m01']/M['m00'])

            if(min_cx <= _cx <= max_cx):

                if(min_cy <= _cy <= max_cy):

                    UI.addToLbox("Contour found within bounds;")
                    UI.addToLbox("_cx: " + str(_cx))
                    UI.addToLbox("_cy: " + str(_cy))
                    UI.addToLbox("Area: " + str(cv2.contourArea(contour)))

                    contour_found = True
                    TestData.setContent(write_result_index, str(cv2.contourArea(contour)))

                    break

        if(not(contour_found)):

            UI.addToLbox("Contour was not found!")

            TestData.setContent(write_result_index, "NOT_FOUND")

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

# Contours smaller than this many raw pixels are treated as noise and ignored by the
# EVALCONT / EVALCONTN detection below.
MIN_CONTOUR_PIXELS = 50

#Shared contour detection for EVALCONT (positive) and EVALCONTN (negative) so the two can
#never drift apart -- they use IDENTICAL detection and differ only in the PASS/FAIL verdict.
#Scans `contours` for the LARGEST (by calibrated area) contour whose centroid lies within
#+/-tol of (cx,cy), after discarding sub-MIN_CONTOUR_PIXELS noise. Returns:
#   in_window : True if at least one qualifying contour's centroid was inside the window
#   area      : calibrated area (raw*cal) of that largest in-window contour, else None
#   centroid  : (x,y) of that contour, else None
#A "valid detection" (used to decide pass/fail) is: in_window and area > minarea.
def _detect_contour_at(contours, cx, cy, tol, cal):

    if contours is None:
        contours = []

    min_cx = max(0, cx - tol)
    min_cy = max(0, cy - tol)
    max_cx = cx + tol
    max_cy = cy + tol

    best_area = None
    best_centroid = None
    in_window_contours = []

    for contour in contours:

        raw = cv2.contourArea(contour)
        if raw < MIN_CONTOUR_PIXELS:            # noise floor
            continue

        M = cv2.moments(contour)
        if M['m00'] == 0:                       # guard against divide-by-zero
            continue

        _cx = int(M['m10'] / M['m00'])
        _cy = int(M['m01'] / M['m00'])

        if not (min_cx <= _cx <= max_cx and min_cy <= _cy <= max_cy):
            continue

        in_window_contours.append(contour)

        area = raw * cal
        if best_area is None or area > best_area:   # keep the largest in-window contour
            best_area = area
            best_centroid = (_cx, _cy)

    # DEBUG: dump the search-window crop (with any in-window contours drawn) for inspection.
    _save_debug_crop(_last_contour_frame, cx, cy, tol, in_window_contours)

    return (best_area is not None, best_area, best_centroid)

#High level function :: Evaluates if a contour in a determined position cx,cy has area large enough
async def EVALCONT(line, UI):

    #0            1        2        3                       4                     5           6
    #ImageProcess EVALCONT *l,c,p   cx,cy,tol,minarea,cal   write_result_index    -           kill_index,test_ID

    #PASS when a valid contour IS present at (cx,cy): centroid within +/-tol AND calibrated
    #area (raw*cal) > minarea. Otherwise FAIL + kill (nothing there, OR a contour there but too small).

    try:

        contour_info = TestData.getContent(line[3]).split(',')

        contours = TestData.getContent(line[2])
        cx = int(contour_info[0])
        cy = int(contour_info[1])
        pixel_tol = int(contour_info[2])
        minarea = int(contour_info[3])
        calibration_value = float(contour_info[4])

        result_index = getTripleIndex(TestData.getContent(line[4]))

        extra_info = TestData.getContent(line[6]).split(',')
        kill_index = extra_info[0]
        test_ID = extra_info[1]

        grid_info = TestData.getContent(line[5])

        in_window, area, centroid = _detect_contour_at(contours, cx, cy, pixel_tol, calibration_value)

        if in_window:
            UI.addToLbox("Contour found within bounds; _cx: " + str(centroid[0]) + " _cy: " + str(centroid[1]))
            UI.addToLbox("Contour area (calibrated): " + str(area))

        if in_window and area > minarea:

            UI.addToLbox("Contour area is within bounds: " + str(area))

            TestData.setContent(result_index[0], str(area))
            TestData.setContent(result_index[1], "PASS")
            TestData.setContent(result_index[2], test_ID)

            if(grid_info == "min"):
                grid_message = test_ID + ";"+str( int(kill_index) + 1 )+";"+str(minarea)+";"+"-;"+str(area)+";PASS"+";-"+";PASS"
            else:
                grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+str(area)+";-"+";-"+";PASS"+";-"+";PASS"

            #grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+str(area)+";-"+";-"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)

        else:

            if in_window:
                reported = str(area)
                grid_area = str(area)
                UI.addToLbox("Contour area is not within bounds: " + str(area))
            else:
                reported = "NOT_FOUND"
                grid_area = "NOT FOUND"
                UI.addToLbox("Contour was not found!")

            TestData.setContent(result_index[0], reported)
            TestData.setContent(result_index[1], "FAIL")
            TestData.setContent(result_index[2], test_ID)

            if(grid_info == "min"):
                grid_message = test_ID + ";"+str( int(kill_index) + 1 )+";"+str(minarea)+";"+"-"+"NOT_FOUND"+";FAIL"+";-"+";FAIL"
            else:
                grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+grid_area+";-"+";-"+";FAIL"+";-"+";FAIL"

            #grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+grid_area+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.kill(kill_index)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#High level function :: Inverse of EVALCONT -- PASS when NO valid contour is present at cx,cy
async def EVALCONTN(line, UI):

    #0            1         2        3                       4                     5           6
    #ImageProcess EVALCONTN *l,c,p   cx,cy,tol,minarea,cal   write_result_index    -           kill_index,test_ID

    #True inverse of EVALCONT: same detection (noise filter + calibration + centroid window),
    #verdict flipped. FAIL + kill when a valid contour IS present at (cx,cy); PASS when absent.

    try:

        contour_info = TestData.getContent(line[3]).split(',')

        contours = TestData.getContent(line[2])
        cx = int(contour_info[0])
        cy = int(contour_info[1])
        pixel_tol = int(contour_info[2])
        minarea = int(contour_info[3])
        calibration_value = float(contour_info[4])

        result_index = getTripleIndex(TestData.getContent(line[4]))

        grid_info = TestData.getContent(line[5])

        extra_info = TestData.getContent(line[6]).split(',')
        kill_index = extra_info[0]
        test_ID = extra_info[1]

        in_window, area, centroid = _detect_contour_at(contours, cx, cy, pixel_tol, calibration_value)

        if in_window and area > minarea:

            UI.addToLbox("Contour found within bounds; _cx: " + str(centroid[0]) + " _cy: " + str(centroid[1]))
            UI.addToLbox("Contour present where none expected, area: " + str(area))

            TestData.setContent(result_index[0], str(area))
            TestData.setContent(result_index[1], "FAIL")
            TestData.setContent(result_index[2], test_ID)

            if(grid_info == "min"):
                grid_message = test_ID + ";"+str( int(kill_index) + 1 )+";"+str(minarea)+";"+"-;"+str(area)+";FAIL"+";-"+";FAIL"
            else:
                grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+str(area)+";-"+";-"+";FAIL"+";-"+";FAIL"

            #grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+str(area)+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.kill(kill_index)

        else:

            UI.addToLbox("Contour was not found!")

            TestData.setContent(result_index[0], "NOT_FOUND")
            TestData.setContent(result_index[1], "PASS")
            TestData.setContent(result_index[2], test_ID)

            if(grid_info == "min"):
                grid_message = test_ID + ";"+str( int(kill_index) + 1 )+";"+str(minarea)+";"+"-;"+"NOT FOUND"+";PASS"+";-"+";PASS"
            else:
                grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+"NOT FOUND"+";-"+";-"+";PASS"+";-"+";PASS"

            #grid_message = test_ID+";"+str(int(kill_index)+1)+";"+str(minarea)+";-"+";"+"-"+";"+"NOT FOUND"+";-"+";-"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#High level function :: Evaluates if the leds color is the required
async def EVALLEDS(line, UI):       

    #0            1           2           3                        4                        5           6
    #ImageProcess EVALLEDS    *l,c,p      coords_index_string      write_result_index       -           kill_index,test_ID

    # CARREGAR IMAGENS
    try:
        frame = getImage("-", TestData.getContent(line[2]), UI)   #frame = getImage(line[2], TestData.getContent(line[3]), UI)   ## DUVIDA -> frame = getImage(line[2], "-", UI)  ????
        #UI.addToLBox("Imagem carregada para EVALLEDS")	
        
        # LER STRINGS COM COORDENADAS

        coords_str = TestData.getContent(line[3])   # Read the string that contains the coordinates for the LEDs
        coords_list = coords_str.split(";")         # Split the string into parts using ";" so each part represents one LED.       USAR ";" OU ","

        target_values = TestData.getContent(line[5]).split(",")
        target_blue = int(target_values[0])
        target_green = int(target_values[1])
        target_red = int(target_values[2])

        grid_info = TestData.getContent(line[5])

        overall_pass = True                         # Start by assuming that all LEDs will pass.
        results_list = []                           # Create an empty list to store the result for each LED.

        # Loop through each LED's coordinate in the list.
        for idx, item in enumerate(coords_list):    
            item = item.strip()                # Remove extra spaces from the beginning and end of the item.
            if not item:          
                continue                       # If the item is empty, move to the next one.

            parts = item.split(',')            # Split the LED coordinate string into parts (expected: "x,y,crop_radius,threshold").
            if len(parts) < 4:                 # If there are fewer than 4 numbers, then the coordinates are incomplete
                overall_pass = False           # Mark overall as failed
                continue                       # Move to the next LED.

            # Try to convert the coordinate parts from text into numbers (integers).
            try:
                x = int(parts[0])              # x-position of the LED.
                y = int(parts[1])              # y-position of the LED.
                crop_radius = int(parts[2])    # The radius to crop the LED area.
                                               # The 4º value can or cant be used (threshold)

            except Exception as ex:
                overall_pass = False
                continue


            # FAZER CROP DO LED 

            x1 = max(x - crop_radius, 0)                # Start at x - crop_radius, but not less than 0.
            y1 = max(y - crop_radius, 0)                # Start at y - crop_radius, but not less than 0.
            x2 = min(x + crop_radius, frame.shape[1])   # End at x + crop_radius, but not more than image width.
            y2 = min(y + crop_radius, frame.shape[0])   # End at y + crop_radius, but not more than image height.

            #UI.addToLbox(f"Crop LED {idx+1}: ({x1},{y1}) a ({x2},{y2})")

            cropped = frame[y1:y2, x1:x2]               # Crop the image using the calculated coordinates.

            if cropped.size == 0:                       # If the crop is empty (no pixels), then there's an error.
                overall_pass = False
                continue
            

            # Save the cropped image to a file.
            #save_path = "C:\\Users\\Admin.ONTPC12\\Desktop\\NGINERepo\\uartxngine\\src\\Results\\" + str(idx) + ".jpg"
            #cv2.imwrite(save_path, cropped)

            # K-MEANS

            # Prepare the crop data for K-means clustering to find the dominant color.

            Z = cropped.reshape((-1, 3))                                                          # Reshape the cropped image into a list of pixels, where each pixel has 3 color values (B, G, R).
            Z = Z.astype('float32')                                                               # Convert the pixel values to float32, which is required for K-means.
            K = 3  # número de clusters                                                           # Define that we want to find 2 clusters (groups of similar colors).
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)              # Set the rules for stopping the K-means algorithm (when to stop iterating).
            ret, label, center = cv2.kmeans(Z, K, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)  # Apply K-means clustering to group the pixels into K clusters.
            center = center.astype('uint8')                                                       # Convert the cluster centers back to 8-bit integers (color values).

            counts = [0]*K                                                                        # Create a list to count how many pixels are in each cluster.
            for l in label: 
                counts[l[0]] += 1                                                                 # Increase the count for the cluster that each pixel belongs to.
            dominant_cluster = counts.index(max(counts))                                          # Find the cluster with the most pixels; this is the dominant color.
            dominant_color_bgr = center[dominant_cluster]                                         # Save the dominant color (in BGR format).

            #UI.addToLbox(f"LED {idx+1} (x={x}, y={y}) - Dominant color (BGR): {dominant_color_bgr}")

            '''
            # Convert the dominant color from BGR to HSV format for easier color checking.
            bgr_1x1 = dominant_color_bgr.reshape(1, 1, 3)
            hsv_1x1 = cv2.cvtColor(bgr_1x1, cv2.COLOR_BGR2HSV)[0][0]

            h, s, v = int(hsv_1x1[0]), int(hsv_1x1[1]), int(hsv_1x1[2])                             # Extract the Hue, Saturation, and Value components.

            #UI.addToLbox(f"LED {idx+1} - HSV: {h, s, v}")


            # Check if the color is what we expect (for example, yellow).
            # In this example, yellow is defined as having a hue between 20 and 40, with saturation and value of at least 100.

            # HSV (Hue, Saturation, Value) Explanation Table:

            # Hue (H) -> Defines the actual color (range: 0-179 in OpenCV)
            #  0 - 10   -> Red  
            # 10 - 20   -> Orange  
            # 20 - 40   -> Yellow  
            # 40 - 80   -> Green  
            # 90 - 130  -> Blue  
            # 140 - 170 -> Purple  
            # 170 - 179 -> Red (wraps around)

            # Saturation (S) -> Defines how vivid or pure the color is (range: 0-255)
            #  0 - 50   -> Faded, white/grayish  
            # 50 - 100  -> Low saturation  
            # 100 - 255 -> Pure and vibrant color

            # Value (V) -> Defines brightness (range: 0-255)
            #  0 - 50   -> Very dark (blackish)  
            # 50 - 150  -> Medium brightness  
            # 150 - 255 -> Very bright

            is_yellow = (20 <= h <= 40) and (s >= 80) and (v >= 50)   # Adjust values in order to get the best result
            if is_yellow:
                led_result = "PASS"
            else:
                led_result = "FAIL"
                overall_pass = False

            #results_list.append(f"LED {idx+1} (x={x}, y={y}): BGR={list(dominant_color_bgr)} -> {led_result}")
            '''

        #target = [50, 220, 235]
        tolerance = 30
        led_result = False
        color = ""

        if(overall_pass):
            
            for cent in center:
                print(cent)
                UI.addToLbox(str(cent))
                if( target_blue - tolerance <= cent[0] <= target_blue + tolerance):
                    color += str(cent[0]) + "-"
                    if( target_green - tolerance <= cent[1] <= target_green + tolerance):
                        color += str(cent[1]) + "-"
                        if( target_red - tolerance <= cent[2] <= target_red + tolerance):
                            color += str(cent[2]) + "-"
                            led_result = True
                            break
        else:

            led_result = False


        # ---------------------------------------------------------------------
        aggregated_result = "\n".join(results_list)                 # Combine all the LED results into a single text string with each LED's result on a new line.
        write_result_index = TestData.getContent(line[4])           # Get the index where the results should be saved.
        result_index = getTripleIndex(write_result_index)           # Generate a list of indices to save multiple results (usually three positions).

        extra_data = TestData.getContent(line[6]).split(',')
        test_ID = extra_data[1]                                     # Define an identifier for the test.
        kill_index = int(extra_data[0])                             # Get the kill_index value, used to terminate the test if needed.

        TestData.setContent(result_index[0], color)     # Save the combined text with all results.
        overall_status = "PASS" if led_result else "FAIL"         # Set the overall status to PASS if everything is good; otherwise, FAIL.
        TestData.setContent(result_index[1], overall_status)        # Save the overall status.
        TestData.setContent(result_index[2], test_ID)               # Save the test identifier.
        
        grid_message = (                                            # Build the final message to display in the grid with all the result details.
            test_ID + ";" +
            str(int(kill_index) + 1) + ";" +
            str(target_blue - tolerance) + "-" + str(target_green - tolerance) + "-" + str(target_red - tolerance) + 
            ";" +
            "-;" + 
            str(target_blue + tolerance) + "-" + str(target_green + tolerance) + "-" + str(target_red + tolerance) + 
            ";" +
            color + ";-;-;" +
            overall_status + ";-;" + overall_status
        )

        #grid_message = test_ID+";"+"0"+";"+grid_param+";-"+";"+"-"+";"+"NOT FOUND"+";-"+";-"+";FAIL"+";-"+";FAIL"

        add2GRID(grid_message, str(kill_index), UI)                      # Send the message to the grid (table) to show the results.

        if not overall_pass:                                        # If any LED did not pass, show a message and kill the test
            UI.addToLbox("LEDS COLOR FAIL")
            TestData.kill(str(kill_index))
        else:                                                       # If all LEDs passed, show a message saying everything is okay.
            UI.addToLbox("PASS")

    except Exception as e:                                          # If an error happens during the process, try to raise an exception with a detailed message.
        # Tratamento de erro
        try:
            raise Exception(line[7] + "::" + str(e))
        except:
            raise Exception(str(e))       


#To be developed..
async def EVALCONTS(line,UI):

    #0            1           2        3               4               5    6
    #ImageProcess EVALCONTS   *l,c,p   cx,cx1,cx2,..   cy0,cy1,cy2,..  tol  minarea0,minarea1,minarea2,..
    print("under development")

async def MASSCROP(line, UI):
    
    #0                  1            2                  3                   4               5
    #ImageProcess       MASSCROP     image_index        crop_centers        crop_radius     indexes_to_save_crops
    #ImageProcess       MASSCROP     *0,0,10            100,200;150,200     100             0,0,1;1,0,1

    try:
        
        frame = getImage("-", TestData.getContent(line[2]), UI)
        crop_centers = TestData.getContent(line[3]).split(';')
        crop_radius = round(int(TestData.getContent(line[4]))/2)
        save_indexes = TestData.getContent(line[5]).split(';')

        for i in range(len(crop_centers)):
            crop_coordinates = crop_centers[i].split(',')
            crop_x = int(crop_coordinates[0])
            crop_y = int(crop_coordinates[1])

            cropped_frame = frame[crop_y - crop_radius :crop_y + crop_radius, crop_x - crop_radius:crop_x + crop_radius]
            TestData.setContentNS(save_indexes[i], cropped_frame)
            cv2.imwrite("C:\\Users\\Admin.ONTPC12\\Desktop\\NGINERepo\\uartxngine\\src\\Results\\" + str(i) + ".jpg", cropped_frame)

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))

#Helpers
def getTripleIndex(base_index):

	values = base_index.split(',')

	triple_index = []

	triple_index.append(base_index)
	triple_index.append(values[0]+','+str(int(values[1])+1)+','+values[2])
	triple_index.append(values[0]+','+str(int(values[1])+2)+','+values[2])

	return triple_index

def add2GRID(grid_message, kill_index, UI):

    if(kill_index == '0'):

        UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

    elif(kill_index == '1'):

        UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

    elif(kill_index == '2'):

        UIManager.SYNCGRID3(["UI","GRID3","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

def getImage(data_info, dir_info, UI):

    if(data_info != '-'):

        UI.addToLbox("Getting image: " + data_info)

        return(TestData.getContent(data_info))

    elif(dir_info != '-'):

        UI.addToLbox("Getting image: " + dir_info)

        return(cv2.imread(dir_info))

def saveImage(data_info, dir_info, frame):

    if(data_info != '-'):

        TestData.setContentNS(data_info, frame)

    elif(dir_info != '-'):

        cv2.imwrite(dir_info, frame)
