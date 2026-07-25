import TestData
import UIManager
import matplotlib.pyplot as plt
import numpy as np
import math

async def ASPOCK1211(line, UI):

    #0              1               2                   3                                         4                       5               6
    #DataProcess    ASPOCK1211      *channel_indexes    result_indexes                            min_curr,max_curr       sample_rate     kill_index
    #DataProcess    ASPOCK1211      *0,0,0;*1,0,0       2,0,0;2,0,1;2,0,2;2,0,3;2,0,4             0.1,0.6                 2000            0

    try:
        
        channel_data_indexes = line[2].split(';')
        channel1_data = TestData.getContent(channel_data_indexes[0])
        channel2_data = TestData.getContent(channel_data_indexes[1])

        result_indexes = TestData.getContent(line[3]).split(';')
        result1_index = getTripleIndex(result_indexes[0])
        result2_index = getTripleIndex(result_indexes[1])

        period_result_index = getTripleIndex(result_indexes[2])
        max_result_index = getTripleIndex(result_indexes[3])
        uptime_result_index = getTripleIndex(result_indexes[4])

        data = [channel1_data, channel2_data]

        curr_limits = TestData.getContent(line[4]).split(',')
        min_current = float(curr_limits[0])
        max_current = float(curr_limits[1])

        sample_rate = int(TestData.getContent(line[5]))
        
        kill_index = TestData.getContent(line[6])

        # Process ai0 (First Channel)
        result_ai0 = process_data([data[0]], sample_rate)

        binary_data_ai0 = result_ai0['binary_data'][0]  # Extract the binary data
        short_pulse_indexes_ai0 = result_ai0['short_pulse_indexes'][0] # Extract the short pulse indexes data

        # Ensure we have a valid crop region (at least two short pulses needed)
        if len(short_pulse_indexes_ai0) < 2:
            print("Not enough short pulses detected in ai0 to define a crop region.")
            TestData.setContent(period_result_index[0], "--")
            TestData.setContent(period_result_index[1], "FAIL")
            TestData.setContent(period_result_index[2], "Period")

            grid_message = "Period"+";"+str(int(kill_index)+1)+";"+"396"+";-"+";"+"484"+";"+"--"+";-"+";ms"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.setContent(max_result_index[0], "--")
            TestData.setContent(max_result_index[1], "FAIL")
            TestData.setContent(max_result_index[2], "Max current value")

            grid_message = "Max Current"+";"+str(int(kill_index)+1)+";"+"0.54"+";-"+";"+"0.66"+";"+"--"+";-"+";A"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.setContent(uptime_result_index[0], "--")
            TestData.setContent(uptime_result_index[1], "FAIL")
            TestData.setContent(uptime_result_index[2], "Uptime")

            grid_message = "Uptime"+";"+str(int(kill_index)+1)+";"+"108"+";-"+";"+"132"+";"+"--"+";-"+";ms"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.setContent(result1_index[0], "--")
            TestData.setContent(result1_index[1], "FAIL")
            TestData.setContent(result1_index[2], "CurrTest")

            grid_message = "CurrTest"+";"+str(int(kill_index)+1)+";"+str(min_current)+";-"+";"+str(max_current)+";"+"--"+";-"+";A"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

            TestData.setContent(result2_index[0], "--")
            TestData.setContent(result2_index[1], "FAIL")
            TestData.setContent(result2_index[2], "SYC")

            grid_message = "SYC"+";"+str(int(kill_index)+1)+";"+"-"+";-"+";"+"-"+";"+"--"+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)
            TestData.kill(kill_index)

            return

        # Define crop region from ai0's pulses
        start_idx = short_pulse_indexes_ai0[0][1] + 1  # Start after first short pulse
        end_idx = short_pulse_indexes_ai0[1][1] + 1    # End after second short pulse

        period = (end_idx - start_idx)/(sample_rate/1000)
        UI.addToLbox("period: " + str(period))

        if(396 <= period <= 484):

            TestData.setContent(period_result_index[0], str(period))
            TestData.setContent(period_result_index[1], "PASS")
            TestData.setContent(period_result_index[2], "Period")

            grid_message = "Period"+";"+str(int(kill_index)+1)+";"+"396"+";-"+";"+"484"+";"+str(period)+";-"+";ms"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)

        else:

            TestData.setContent(period_result_index[0], str(period))
            TestData.setContent(period_result_index[1], "FAIL")
            TestData.setContent(period_result_index[2], "Period")

            grid_message = "Period"+";"+str(int(kill_index)+1)+";"+"396"+";-"+";"+"484"+";"+str(period)+";-"+";ms"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

        # Print average sum calculation within crop region
        segment = [x * 0.2 for x in data[0][start_idx:end_idx]]
        measured_current = round(math.sqrt(sum(x * x for x in segment) / (end_idx - start_idx)), 3)
        #measured_current = round(sum(data[0][start_idx:end_idx])/(end_idx - start_idx)*0.2, 3)

        max_value = round(max(data[0][start_idx:end_idx])/5, 3)
        UI.addToLbox("Max value: " +  str(max_value))

        if(0.54 <= max_value <= 0.66):

            TestData.setContent(max_result_index[0], str(max_value))
            TestData.setContent(max_result_index[1], "PASS")
            TestData.setContent(max_result_index[2], "Max current value")

            grid_message = "Max Current"+";"+str(int(kill_index)+1)+";"+"0.54"+";-"+";"+"0.66"+";"+str(max_value)+";-"+";A"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)

        else:

            TestData.setContent(max_result_index[0], str(max_value))
            TestData.setContent(max_result_index[1], "FAIL")
            TestData.setContent(max_result_index[2], "Max current value")

            grid_message = "Max Current"+";"+str(int(kill_index)+1)+";"+"0.54"+";-"+";"+"0.66"+";"+str(max_value)+";-"+";A"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

        uptime = count_higher_than_threshold(data[0][start_idx:end_idx], 2.7)/(sample_rate/1000)
        UI.addToLbox("Uptime: " + str(uptime))

        if(108 <= uptime <= 132):

            TestData.setContent(uptime_result_index[0], str(uptime))
            TestData.setContent(uptime_result_index[1], "PASS")
            TestData.setContent(uptime_result_index[2], "Uptime")

            grid_message = "Uptime"+";"+str(int(kill_index)+1)+";"+"108"+";-"+";"+"132"+";"+str(uptime)+";-"+";ms"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)

        else:

            TestData.setContent(uptime_result_index[0], str(uptime))
            TestData.setContent(uptime_result_index[1], "FAIL")
            TestData.setContent(uptime_result_index[2], "Uptime")

            grid_message = "Uptime"+";"+str(int(kill_index)+1)+";"+"108"+";-"+";"+"132"+";"+str(uptime)+";-"+";ms"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)

        #print("Sum: " + str(sum(data[0][start_idx:end_idx])/(end_idx - start_idx)*0.2))
        if min_current <= measured_current <= max_current:

            TestData.setContent(result1_index[0], str(measured_current))
            TestData.setContent(result1_index[1], "PASS")
            TestData.setContent(result1_index[2], "CurrTest")

            grid_message = "CurrTest"+";"+str(int(kill_index)+1)+";"+str(min_current)+";-"+";"+str(max_current)+";"+str(measured_current)+";-"+";A"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)
        else:

            TestData.setContent(result1_index[0], str(measured_current))
            TestData.setContent(result1_index[1], "FAIL")
            TestData.setContent(result1_index[2], "CurrTest")

            grid_message = "CurrTest"+";"+str(int(kill_index)+1)+";"+str(min_current)+";-"+";"+str(max_current)+";"+str(measured_current)+";-"+";A"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)
            TestData.kill(kill_index)

        segment = [x * 0.2 for x in data[0][start_idx:end_idx]]
        rms_curr = round(math.sqrt(sum(x * x for x in segment) / (end_idx - start_idx)), 3)
        
        UI.addToLbox("Current: " + str(measured_current))
        UI.addToLbox("RMS Current: " + str(rms_curr))

        # Crop both channels based on ai0's crop range
        cropped_ai0 = data[0][start_idx:end_idx + 1]
        cropped_ai1 = data[1][start_idx:end_idx + 1]

        # Apply binary filter on ai1 with a 4V threshold
        binary_ai1 = [1 if value >= 4.0 else 0 for value in cropped_ai1]

        # Find transition points where ai1 goes 1 → 0 and ai0 goes 0 → 1 (with ±5 sample tolerance)
        transition_points = []
        tolerance = 5  # Allow up to 5 sample deviation

        for i in range(1, len(binary_ai1)):
            if binary_ai1[i - 1] == 1 and binary_ai1[i] == 0:  # ai1 1 → 0 transition detected
                # Search for ai0 0 → 1 transition within ±5 samples
                for j in range(max(0, i - tolerance), min(len(binary_data_ai0), i + tolerance + 1)):
                    if binary_data_ai0[start_idx + j - 1] == 0 and binary_data_ai0[start_idx + j] == 1:
                        transition_points.append((i, j))  # Store (ai1 transition index, ai0 transition index)
                        break  # Stop searching once we find a valid match

        UI.addToLbox("Transition points: " + str(transition_points))

        if(len(transition_points) > 0):

            TestData.setContent(result2_index[0], str(transition_points))
            TestData.setContent(result2_index[1], "PASS")
            TestData.setContent(result2_index[2], "SYC")
            
            grid_message = "SYC"+";"+str(int(kill_index)+1)+";"+"-"+";-"+";"+"-"+";"+str(transition_points[0])+";-"+";-"+";PASS"+";-"+";PASS"
            add2GRID(grid_message, kill_index, UI)
        else:

            TestData.setContent(result2_index[0], str(transition_points))
            TestData.setContent(result2_index[1], "FAIL")
            TestData.setContent(result2_index[2], "SYC")

            grid_message = "SYC"+";"+str(int(kill_index)+1)+";"+"-"+";-"+";"+"-"+";"+str(transition_points[0])+";-"+";-"+";FAIL"+";-"+";FAIL"
            add2GRID(grid_message, kill_index, UI)
            TestData.kill(kill_index)

        '''
        plt.figure(figsize=(12, 6))

        time_cropped = [t / sample_rate for t in range(len(cropped_ai0))]

        # Plot original ai0
        plt.plot(time_cropped, cropped_ai0 * 0.2, label="Cropped ai0 (1V Threshold)", alpha=1)

        # Plot original ai1
        plt.plot(time_cropped, cropped_ai1, label="Cropped ai1 (4V Threshold)", alpha=1)

        # Mark transition points
        for t1, t0 in transition_points:
            plt.axvline(x=t1 / sample_rate, color='red', linestyle='--', label="ai1 1→0 Transition" if t1 == transition_points[0][0] else "")
            plt.axvline(x=t0 / sample_rate, color='blue', linestyle='--', label="ai0 0→1 Transition" if t0 == transition_points[0][1] else "")

        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.title("UUT" + str(int(kill_index) + 1) + " Cropped Data and Transition Points (with Tolerance)")
        plt.legend()
        plot_path = TestData.getContent("*2,0,24") + "/UUT" + str(int(kill_index) + 1) + ".png"
        plt.grid()
        plt.savefig(plot_path)

        #plt.show(block=False)
        '''

        fig, ax1 = plt.subplots(figsize=(12, 6))
        time_cropped = [t / sample_rate for t in range(len(cropped_ai0))]

        # Plot cropped_ai0 on the left y-axis (scaled by 0.2)
        ax1.plot(time_cropped, [x * 0.2 for x in cropped_ai0], label="Current (A)", alpha=1, color='blue')
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("Current (A)", color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')

        # Set x-axis ticks to every 20ms (0.02 s)
        ax1.set_xticks(np.arange(0, max(time_cropped) + 0.02, 0.02))

        # Set the left y-axis limit to [0, 1]
        ax1.set_ylim(-0.1, 1)

        # Create a second y-axis for cropped_ai1
        ax2 = ax1.twinx()
        ax2.plot(time_cropped, cropped_ai1, label="SYC (V)", alpha=1, color='red')
        ax2.set_ylabel("SYC (V)", color='red')
        ax2.tick_params(axis='y', labelcolor='red')

        # Mark transition points on the common x-axis
        for t1, t0 in transition_points:
            # Draw vertical lines on the left axis (they will appear on both axes)
            ax1.axvline(x=t1 / sample_rate, color='red', linestyle='--',
                        label="ai1 1→0 Transition" if t1 == transition_points[0][0] else "")
            ax1.axvline(x=t0 / sample_rate, color='blue', linestyle='--',
                        label="ai0 0→1 Transition" if t0 == transition_points[0][1] else "")

        # Combine legends from both axes
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

        plt.title("UUT" + str(int(kill_index) + 1) + " Cropped Data and Transition Points (with Tolerance)")
        plt.grid()

        plot_path = TestData.getContent("*2,0,24") + "/UUT" + str(int(kill_index) + 1) + ".png"
        plt.savefig(plot_path)
        #plt.show()

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))
    


#Helpers

def count_higher_than_threshold(values: list, threshold: float) -> int:
    """
    Returns the count of values in the list that are higher than the given threshold.

    :param values: List of numeric values.
    :param threshold: The threshold value to compare against.
    :return: Count of values greater than the threshold.
    """
    return sum(1 for value in values if value > threshold)

def process_data(data, sample_rate, pulse_duration_threshold=0.025):
    """
    Process the acquired data to:
    1. Apply a binary filter where values below 1V become 0, and values >= 1V become 1.
    2. Find the indexes of samples between two short pulses (shorter than the specified duration),
       ensuring that the search starts only when a 0 is first encountered.

    Parameters:
        data (list of lists): Acquired data from multiple channels.
        sample_rate (int): Sampling rate in Hz.
        pulse_duration_threshold (float): Maximum pulse duration in seconds (default 25ms).

    Returns:
        dict: Processed data containing:
            - 'binary_data': Binary-filtered data for each channel.
            - 'short_pulse_indexes': List of tuples for each channel with start and end indexes of short pulses.
    """
    binary_data = []
    short_pulse_indexes = []
    
    # Convert pulse duration threshold to number of samples
    max_pulse_samples = int(pulse_duration_threshold * sample_rate)

    for channel_data in data:
        # Apply binary filter: Values >= 1V -> 1, otherwise -> 0
        binary_channel = [1 if value >= 1.0 else 0 for value in channel_data]
        binary_data.append(binary_channel)

        pulse_indexes = []
        start_idx = None
        search_started = False  

        for idx, value in enumerate(binary_channel):
            if not search_started:
                if value == 0:
                    search_started = True  # Start detecting pulses only after encountering first 0
                continue  

            if value == 1 and start_idx is None and binary_channel[idx - 1] == 0:
                start_idx = idx  # Mark pulse start index
            elif value == 0 and start_idx is not None:
                pulse_length = idx - start_idx
                if pulse_length <= max_pulse_samples:
                    pulse_indexes.append((start_idx, idx - 1))  # Store start and end indexes of short pulse
                start_idx = None

        # Handle last pulse if the signal ends in a high state
        if start_idx is not None:
            pulse_length = len(binary_channel) - start_idx
            if pulse_length <= max_pulse_samples:
                pulse_indexes.append((start_idx, len(binary_channel) - 1))

        short_pulse_indexes.append(pulse_indexes)

    return {
        'binary_data': binary_data,
        'short_pulse_indexes': short_pulse_indexes
    }

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