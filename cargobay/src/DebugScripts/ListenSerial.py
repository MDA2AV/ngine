import serial

def utf8_char_to_bits(char):
    # Step 1: Encode the character to UTF-8 bytes
    utf8_bytes = char.encode('utf-8')

    # Step 2: Convert each byte to its binary representation
    bits = ''.join(format(byte, '08b') for byte in utf8_bytes)

    return bits


def is_bit_set(bit_array, index):
    """
    Check if the bit at the given index is set to 1.

    Parameters:
    bit_array (str): A string representing the byte as a bit array (e.g., '01100001').
    index (int): The zero-based index of the bit to check.

    Returns:
    bool: True if the bit at the given index is 1, False otherwise.
    """
    if index < 0 or index >= len(bit_array):
        raise ValueError("Index out of range")

    return bit_array[index] == '1'

def read(bit_index):
	serial_port = 'COM5'
	baud_rate = 115200  # Set the baud rate according to your device's specification

	# Initialize serial connection
	ser = serial.Serial(serial_port, baud_rate)

	while True:
		if ser.in_waiting > 0:
			message = ser.read().decode('utf-8').strip()
			print(message)
			bits = utf8_char_to_bits(message)
			return f'{is_bit_set(bits, bit_index)}'
			break

def continuous_read():
    serial_port = 'COM5'
    baud_rate = 115200  # Set the baud rate according to your device's specification

    # Initialize serial connection
    ser = serial.Serial(serial_port, baud_rate)

    while True:
        if ser.in_waiting > 0:
            message = ser.read().decode('utf-8').strip()
            print(message)
            bits = utf8_char_to_bits(message)
            print(bits)

continuous_read()

#print(f'Status bit result: {read(1)}')
#print(f'West result: {read(7)}')
#print(f'East bit result: {read(5)}')


'''
# Replace 'COM3' with your serial port name
# For Linux, it might be something like '/dev/ttyUSB0'
serial_port = 'COM5'
baud_rate = 115200  # Set the baud rate according to your device's specification

# Initialize serial connection
ser = serial.Serial(serial_port, baud_rate)

print(f'Listening on {serial_port} at {baud_rate} baud rate...')

try:
    while True:
    	if ser.in_waiting > 0:
    		# Read data from serial port
    		message = ser.read().decode('utf-8').strip()
    		#message = ser.read()
    		print(f'Received message: {message}')
    		bits = utf8_char_to_bits(message)
    		print(f'The binary representation of "{message}" is: {bits}')
except KeyboardInterrupt:
    print('Exiting...')
finally:
    # Close the serial connection when the program exits
    ser.close()
'''