from nidaqmx.constants import AcquisitionType
import nidaqmx
import matplotlib.pyplot as plt
import asyncio
import UIManager
import TestData


async def ACQUIRE(line, UI):
    
    #0      1           2               3                   4                               5
    #Nidaq  ACQUIRE     device_name     channels            sample_rate(Hz),num_samples     indexes to store data 
    #Nidaq  ACQUIRE     Dev1            ai0,ai1,ai2,ai3     1000,1000                       0,0,0;1,0,0;2,0,0;3,0,0

    try:
        device_name = TestData.getContent(line[2])

        channel_parts = TestData.getContent(line[3]).split(',')
        channels = [f"{device_name}/{channel}" for channel in channel_parts]

        sample_data = TestData.getContent(line[4]).split(',')
        sample_rate = int(sample_data[0])
        num_samples = int(sample_data[1])

        store_indexes = TestData.getContent(line[5]).split(';')

        # Configure the parameters
        #device_name = "Dev1"  # Replace with your device name as shown in NI MAX
        #channels = [f"{device_name}/ai0", f"{device_name}/ai1"]  # List of channels
        #sample_rate = 500  # Sampling rate in Hz
        #num_samples = 500  # Number of samples to read

        # Create a task to read data
        with nidaqmx.Task() as task:
            # Add analog input channels
            task.ai_channels.add_ai_voltage_chan(
                ",".join(channels)  # Add all channels
            )

            # Configure the sample clock
            task.timing.cfg_samp_clk_timing(
                rate=sample_rate,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=num_samples
            )

            # Start the task
            UI.addToLbox("Acquiring data from multiple channels...")
            task.start()

            # Read the data from all channels
            data = task.read(number_of_samples_per_channel=num_samples)

            # Stop the task
            task.stop()

            # Store the acquired data to eahc channel index
            for i, channel_data in enumerate(data):
                TestData.setContentNS(store_indexes[i], channel_data)

    except Exception as e:
        raise Exception(line[7] + "::" + str(e))

    # Now, `data` contains a list where each element corresponds to the data from one channel.
    # Plot the data
    #print("Plotting data...")
    #time = [t / sample_rate for t in range(num_samples)]  # Create a time axis

    #plt.figure(figsize=(12, 6))
    #for i, channel_data in enumerate(data):
    #    plt.plot(time, channel_data, label=f"Channel {channels[i]}")

    #plt.xlabel("Time (s)")
    #plt.ylabel("Voltage (V)")
    #plt.title("Acquired Data from Multiple Channels")
    #plt.legend()
    #plt.grid()
    #plt.show()