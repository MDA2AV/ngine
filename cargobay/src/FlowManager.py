import TestData
import UIManager
import time
import asyncio
import os
import json
from datetime import datetime


#JUMPS
#Jump to a label based on a comparison criteria.

#Jump to a label.
async def J(line, UI):

	#Flow J "LabelName"

	try:

		UI.addToLbox("Jumping to " + str(line[2]))

		jump(line[2])

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if data stored value contains string
async def JC(line, UI):

	#0    1  2         3      4
	#Flow JC LabelName *l,c,p *l,c,p
	#Flow JC LabelName *l,c,p string

	#if 3 contains 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		if(line4 in line3):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if data stored value contains multiple strings
async def JCM(line, UI):

	#0    1   2         3      4
	#Flow JCM LabelName *l,c,p *l,c,p
	#Flow JCM LabelName *l,c,p string
	#Flow JCM LabelName *l,c,p word1;word2

	#if 3 contains 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		words = line4.split(';')

		for word in words:

			if(not(word in line3)):

				UI.addToLbox("NOT Jumping to " + str(line[2]))

				return

		UI.addToLbox("Jumping to " + str(line[2]))

		jump(line[2])

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if data stored value does not contain string
async def JNC(line, UI):

	#0    1   2         3      4
	#Flow JNC LabelName *l,c,p *l,c,p
	#Flow JNC LabelName *l,c,p string

	#if 3 does not contain 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		if ( not(line4 in line3) ):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is equal to a constant or a data stored value.
async def JE(line, UI):

	#0    1  2         3      4
	#Flow JE LabelName *l,c,p *l,c,p
	#Flow JE LabelName *l,c,p string

	#if 3 is equal to 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		if(line3 == line4):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is not equal to a constant or a data stored value.
async def JNE(line, UI):

	#0    1   2         3      4
	#Flow JNE LabelName *l,c,p *l,c,p
	#Flow JNE LabelName *l,c,p string

	#if 3 is equal to 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		if( not(line3 == line4) ):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#JUMPS FROM HERE WORK WITH STRING_FLOATS ONLY

#Same as JE but the target value of comparison has a set tolerance, tolerance may be a constant set value or a data stored value.
async def JET(line, UI):

	#0    1   2         3             4             5
	#Flow JET LabelName string_float  string_float  string_float
	#Flow JET LabelName *l,c,p        *l,c,p        *l,c,p

	#if 3 is equal to 4 with tolerance 5, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])
		line5 = TestData.getContent(line[5])

		base = float(line3)
		target = float(line4)
		tol = float(line5)

		target_high = target*(1.0 + tol)
		target_low = target*(1.0 - tol)

		if( (base >= target_low) and (base <= target_high) ):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Same as JNE but the target value of comparison has a set tolerance, tolerance may be a constant set value or a data stored value.
async def JNET(line, UI):

	#0    1    2         3             4             5
	#Flow JNET LabelName string_float  string_float  string_float
	#Flow JNET LabelName *l,c,p        *l,c,p        *l,c,p

	#if 3 is not equal to 4 with tolerance 5, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])
		line5 = TestData.getContent(line[5])

		base = float(line3)
		target = float(line4)
		tol = float(line5)

		target_high = target*(1.0 + tol)
		target_low = target*(1.0 - tol)

		if( not ((base > target_low) and (base < target_high)) ):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is greater than a constant or a data stored value.
async def JG(line, UI):

	#0    1  2         3            4
	#Flow JG LabelName *l,c,p       *l,c,p
	#Flow JG LabelName string_float string_float

	#if 3 is greater than 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		base = float(line3)
		target = float(line4)

		if(base > target):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is lower than a constant or a data stored value.
async def JL(line, UI):

	#0    1  2         3            4
	#Flow JL LabelName *l,c,p       *l,c,p
	#Flow JL LabelName string_float string_float

	#if 3 is lesser than 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		base = to_float(line3)
		target = to_float(line4)

		if(base < target):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is greater or equal than a constant or a data stored value.
async def JGE(line, UI):

	#0    1   2         3            4
	#Flow JGE LabelName *l,c,p       *l,c,p
	#Flow JGE LabelName string_float string_float

	#if 3 is greater or equal than 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		base = float(line3)
		target = float(line4)

		if(base >= target):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Jump to a label if a data stored value is lower or equal than a constant or a data stored value.
async def JLE(line, UI):

	#0    1   2         3            4
	#Flow JLE LabelName *l,c,p       *l,c,p
	#Flow JLE LabelName string_float string_float

	#if 3 is lesser or equal than 4, jump 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		base = float(line3)
		target = float(line4)

		if(base <= target):

			UI.addToLbox("Jumping to " + str(line[2]))

			jump(line[2])

		else:

			UI.addToLbox("NOT Jumping to " + str(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))





#Store a string element to the data.
async def STORE(line, UI):

	#0    1     2             3
	#Flow STORE stringtostore l,c,p

	line2 = TestData.getContent(line[2])

	try:

		UI.addToLbox("Storing " + str(line2) + " at data " + str(line[3]))

		TestData.setContent(line[3], line2)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Store a composed string element to the data.
async def STOREF(line, UI):

	#0    1      2             3
	#Flow STOREF stringtostore l,c,p

	# *3 = stringtostore

	#stringtostore: this is a %0 string;1,0,0
	#*1,0,0 = short
	#stringtostore: this is a short string

	#stringtostore: this is a %0 string, %1;*1,0,0;*1,0,1
	#*1,0,0 = short
	#*1,0,1 = yikes
	#stringtostore: this is a short string, yikes

	try:

		UI.addToLbox("Adding " + str(line[2]) + " to data " + str(line[3]))

		split_string = line[2].split(';')

		args = split_string[1:len(split_string)]

		counter = 0

		result_string = split_string[0]

		for i in range(len(split_string[0])):

			if( (split_string[0][i]) == '%'):

				UI.addToLbox(str(counter) + " " + str(i))

				result_string = result_string.replace("%" + str(counter), TestData.getContent(args[counter]) )

				counter = counter + 1

		TestData.setContent(line[3], result_string)

		UI.addToLbox(line[3] + " = " + result_string)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Copy the contents of a data stored string value to another data stored string value.
async def COPY(line, UI):

	#0    1    2         3
	#Flow COPY *l,c,p to l,c,p

	try:

		UI.addToLbox("Copying data *" + str(line[2]) + " to data " + str(line[3]))

		TestData.setContent(line[3], TestData.getContent(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Label, reached a label.
async def LABEL(line, UI):

	#Flow Label "LabelName" background

	try:

		UI.addToLbox("Label " + str(line[2]) + " was reached.")

		if(line[3] != "-"):

			UI.frames[0].status_label.configure(text = line[3])

		if(line[5] != "-"):

			UI.frames[0].status_label.configure(fg_color = line[5])

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Delay, add a delay
async def DELAY(line, UI):

	#Flow DELAY delay_in_seconds
	try:

		UI.addToLbox("Delay " + str(line[2]) + " seconds.")

		await asyncio.sleep(float(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Add two values and save to data.
async def ADD(line, UI):

	#0    1   2            3              4
	#Flow ADD l,c,p        *l,c,p         *l,c,p
	#Flow ADD string_float string_float   string_float

	# 2 = 3 + 4

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		left = float(line3)
		right = float(line4)

		TestData.setContent(line[2], str(left + right))

		UI.addToLbox(line[2] + " = " + line3 + " + " + line4 + " = " + TestData.getData(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Subtract two values and save to data.
async def SUB(line, UI):

	#0    1   2            3              4
	#Flow SUB l,c,p        *l,c,p         *l,c,p
	#Flow SUB string_float string_float   string_float

	# 2 = 3 - 4

	try:

		UI.addToLbox(line[2] + " = " + line[3] + " - " + line[4])

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		left = float(line3)
		right = float(line4)

		TestData.setContent(line[2], str(left - right))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Multiply two values and save to data.
async def MULT(line, UI):

	#0    1    2            3              4
	#Flow MULT l,c,p        *l,c,p         *l,c,p
	#Flow MULT string_float string_float   string_float

	# 2 = 3 * 4

	try:

		UI.addToLbox(line[2] + " = " + line[3] + " * " + line[4])

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		left = float(line3)
		right = float(line4)

		TestData.setContent(line[2], str(left * right))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Divide two values and save to data.
async def DIV(line, UI):

	#0    1   2            3              4
	#Flow DIV l,c,p        *l,c,p         *l,c,p
	#Flow DIV string_float string_float   string_float

	# 2 = 3 / 4

	try:

		UI.addToLbox(line[2] + " = " + line[3] + " / " + line[4])

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		left = float(line3)
		right = float(line4)

		TestData.setContent(line[2], str(left / right))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Check if two strings are equal and store a string at data if true, or a string at data if false.
async def EQUAL(line, UI):

	#0    1     2      3      4     5      6
	#Flow EQUAL *l,c,p *l,c,p l,c,p *l,c,p *l,c,p
	#Flow EQUAL string string l,c,p string string

	#if 2 is equal to 3, *4 = 5
	#if 2 is not equal to 3, *4 = 6

	#4 is a data adress l,c,p

	try:

		line2 = TestData.getContent(line[2])
		line3 = TestData.getContent(line[3])
		line5 = TestData.getContent(line[5])
		line6 = TestData.getContent(line[6])

		if(line2 == line3):

			TestData.setContent(line[4], line5)

		else:

			TestData.setContent(line[4], line6)


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Check if two strings are equal and store a string at data if true, or a string at data if false.
async def CONTAIN(line, UI):

	#0    1       2      3      4     5      6
	#Flow CONTAIN *l,c,p *l,c,p l,c,p *l,c,p *l,c,p
	#Flow CONTAIN string string l,c,p string string

	#if 2 contains 3, *4 = 5
	#if 2 does not contain 3, *4 = 6

	try:

		line2 = TestData.getContent(line[2])
		line3 = TestData.getContent(line[3])
		line5 = TestData.getContent(line[5])
		line6 = TestData.getContent(line[6])

		if(line3 in line2):

			TestData.setContent(line[4], line5)

		else:

			TestData.setContent(line[4], line6)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Replace a substring in a string with another string
async def REPLACE(line, UI):

	#0    1       2     3      4
	#Flow REPLACE l,c,p *l,c,p *l,c,p

	#2.replace(3,4)  Replace 3 with 4 at 2

	try:

		line3 = TestData.getContent(line[3])
		line4 = TestData.getContent(line[4])

		idx = TestData.getIndex(line[2])

		temp = TestData[idx[0]][idx[1]][idx[2]]
		temp = temp.replace(line3, line4)

		TestData.setContent(line[2], temp)

		UI.addToLbox(line[2] + " = " + line[2] + ".replace(" + line3 + ", " + line4 + ") = " + TestData.getContent(line[2]))

	except Exception as e:

 		raise Exception(line[7] + "::" + str(e))

#Replace a substring in a string with another string
async def SUBSTRING(line, UI):

	#0    1         2      3     4    5
	#Flow SUBSTRING *l,c,p START END  l,c,p

	try:

		target = TestData.getContent(line[2])
		start = int(TestData.getContent(line[3]))
		save_index = TestData.getContent(line[5])

		end = TestData.getContent(line[4])
		if(end=="END"):
			end = len(target)
		else:
			end = int(end)

		TestData.setContent(save_index, target[start:end])

		UI.addToLbox(line[5] + " = " + target[start:end])

	except Exception as e:

 		raise Exception(line[7] + "::" + str(e))

#Count how many times a substring occurs in a string and save that value
async def COUNT(line, UI):

	#0    1     2     3      4
	#Flow COUNT *l,c,p *l,c,p l,c,p
	#Count how many times 3 happens in 2 and save that value at 4

	line2 = TestData.getContent(line[2])
	line3 = TestData.getContent(line[3])

	try:

		temp = line2.count(line3)

		TestData.setContent(line[4], str(temp))

		UI.addToLbox("input.count(" + line[3] + ") = " + str(temp) )

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Create, modify and get from an Array, this array is stored at data and may be interacted with through indexes.
async def ARRAY(line, UI):

	#0    1     2     3       4           5

	#Flow ARRAY Init  l,c,p   size

	#Flow ARRAY Store array   array_index value_to_store
	#Flow ARRAY Store l,c,p  *l,c,p      *l,c,p

	#Flow ARRAY Get   array   array_index adress_to_store
	#Flow ARRAY Get   *l,c,p  *l,c,p      l,c,p

	#Flow ARRAY Print *l,c,p


	try:

		argument = line[2]

		match argument:

			case "Init":

				UI.addToLbox("Creating ARRAY at " + line[3]+".")

				TestData.setContent(line[3], ([None] * int(line[4])) )

				return

			case "Store":

				idx = TestData.getIndex(line[3])

				array_idx = TestData.getContent(line[4])

				value = TestData.getContent(line[5])

				(TestData.data[idx[0]][idx[1]][idx[2]])[int(array_idx)] = value

				UI.addToLbox(line[3] + "[" + array_idx + "] = " + value)

				return

			case "Get":



				TestData.setContent(line[5], TestData.getContent(line[3])[ int(TestData.getContent(line[4])) ])

				UI.addToLbox(line[5] + " = " + line[3] + "[" + line[4] + "]")

				return

			case "Print":

				UI.addToLbox("Printing " + line[3] + "..")

				array = TestData.getContent(line[3])

				for i in range(len(array)):

					UI.addToLbox(str(i) + ">> " + str(array[i]))

				return

			case "default":

				raise Exception("Invalid match argument.")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Read the contents of a text file to data
async def READTXT(line,UI):

	#0    1       2   3     4
	#Flow READTXT dir l,c,p output?

	idx = TestData.getIndex(line[3])

	try:

		UI.addToLbox("Reading " + line[2] + "..")

		with open(line[2], "r") as f:

			#TestData.data[idx[0]][idx[1]][idx[2]] = f.readlines()
			lines = f.readlines()

			TestData.data[idx[0]][idx[1]][idx[2]] = ""
			for _line in lines:

				TestData.data[idx[0]][idx[1]][idx[2]] = TestData.data[idx[0]][idx[1]][idx[2]] + _line

		if(line[4] == "yes"):

			UI.addToLbox(TestData.data[idx[0]][idx[1]][idx[2]])

			#UI.addToLbox(line[2] + " contents: ")

			#for _line in TestData.data[idx[0]][idx[1]][idx[2]]:

			#	UI.addToLbox(_line.replace("\n",""))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Write the contents of data to a text file
async def WRITETXT(line, UI):

	#0	  1        2   3      4
	#Flow WRITETXT dir *l,c,p output?

	line3 = TestData.getContent(line[3])
	line2 = TestData.getContent(line[2])

	try:

		filename = line2

		written = ""

		with open(filename, 'w') as f:

			for _line in line3:

				f.write(_line)
				written = written + _line


		#print("line[4]: " + line[4])
		if(line[4] == "yes"):
			#print("Inside if")
			#print(line3)
			#print(line2)
			UI.addToLbox(written +  " written to " + line2)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Append the contents of data to a text file
async def APPENDTXT(line, UI):

	#0	  1         2   3      4
	#Flow APPENDTXT dir *l,c,p ouput?

	line3 = TestData.getContent(line[3])
	line2 = TestData.getContent(line[2])

	try:

		filename = line2

		with open(filename, 'a') as f:

			for _line in line3:

				f.write(_line)

		if(line[4] == "yes"):

			UI.addToLbox(line[3] +  " appended to " + line2)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Delete a file
async def DELFILE(line, UI):

	#0    1       2
	#Flow DELFILE filename

	line2 = TestData.getContent(line[2])

	try:

		os.remove(line2)
		UI.addToLbox("Deleted file: " + line2)

	except Exception as e:

		UI.addToLbox("Somethign went wrong deleting " + line2 + ".")

#Create a directory (WINDOWS)
async def CREATEDIR(line,UI):

	#0    1         2
	#Flow CREATEDIR dir

	dir = TestData.getContent(line[2])

	# checking if the directory demo_folder
	# exist or not.
	if not os.path.exists(dir):

		os.makedirs(dir)
		UI.addToLbox("Directory created: " + dir)

#Create a directory (LINUX)
async def MAKEDIR(line, UI):

	#0    1       2
	#Flow MAKEDIR dir

	line2 = TestData.getContent(line[2])
	isExist = os.path.exists(line2)

	if not isExist:

		os.mkdir(line2)
		UI.addToLbox("Directory created: " + line2)

#Evalue a float value if is inside limits
async def EVALIM(line, UI):

	#0    1      2       3                     4        5                    6
	#Flow EVALIM value   lower_lim,upper_lim   l,c,p    jump_good,jump_bad   arg

	line2 = TestData.getContent(line[2])
	line3 = TestData.getContent(line[3])
	line4 = TestData.getContent(line[4])
	line5 = TestData.getContent(line[5])
	line6 = TestData.getContent(line[6])

	value = float(line2)

	limits = line3.split(',')
	lower_limit = float(limits[0])
	upper_limit = float(limits[1])

	idx = line4.split(',')

	jumps = line5.split(',')

	arg = line6

	if(lower_limit <= value <= upper_limit):

		idx0 = idx[0] + ",0," + idx[2]
		idx1 = idx[0] + ",1," + idx[2]
		idx2 = idx[0] + ",2," + idx[2]

		TestData.setContent(idx0, str(value))
		UI.addToLbox(idx0 + " = " + str(value))

		TestData.setContent(idx1, "PASS")
		UI.addToLbox(idx1 + " = PASS")

		TestData.setContent(idx2, arg)
		UI.addToLbox(idx2 + " = " + arg)

		jump(jumps[0])

	else:

		idx0 = idx[0] + ",0," + idx[2]
		idx1 = idx[0] + ",1," + idx[2]
		idx2 = idx[0] + ",2," + idx[2]

		TestData.setContent(idx0, str(value))
		UI.addToLbox(idx0 + " = " + str(value))

		TestData.setContent(idx1, "FAIL")
		UI.addToLbox(idx1 + " = FAIL")

		TestData.setContent(idx2, arg)
		UI.addToLbox(idx2 + " = " + arg)

		jump(jumps[1])

#High level evaluation if a float is inside test limits
async def EVAFLOAT(line,UI):

	#0    1        2                    3                        4                   5           6
	#Flow EVAFLOAT lower_lim,upper_lim  under_evaluation_float   write_result_index  grid_info   kill_index,test_ID
	#Flow EVAFLOAT 3.2,3.4              *0,0,1                   0,0,1;0,1,1;0,2,1   min         0,UC5V

	try:

		limits = line[2].split(',')
		lower_lim = float(limits[0])
		upper_lim = float(limits[1])

		result_index = TestData.getContent(line[4])
		result_index =  result_index.split(';')

		grid_info = TestData.getContent(line[5])

		extra_info = TestData.getContent(line[6])
		extra_info = extra_info.split(',')
		test_id = extra_info[1]
		kill_index = extra_info[0]

		try:

			evaluating_float = float(TestData.getContent(line[3]))

		except Exception as x:

			TestData.setContent(result_index[0], "None")
			TestData.setContent(result_index[1], "FAIL")
			TestData.setContent(result_index[2], test_id)

			if(grid_info == "min"):
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";"+str(upper_lim)+"None"+";FAIL"+";-"+";FAIL"
			else:
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";-"+";"+str(upper_lim)+";"+"None"+";-"+";-"+";FAIL"+";-"+";FAIL"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "2"):

				UIManager.SYNCGRID3(["UI","GRID3","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "3"):

				UIManager.SYNCGRID4(["UI","GRID4","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			TestData.kill(kill_index)

			return

		if( (evaluating_float <= upper_lim) and (evaluating_float >= lower_lim) ):

			TestData.setContent(result_index[0], str(evaluating_float))
			TestData.setContent(result_index[1], "PASS")
			TestData.setContent(result_index[2], test_id)

			if(grid_info == "min"):
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";"+str(upper_lim)+";"+str(evaluating_float)+";PASS"+";-"+";PASS"
			else:
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";-"+";"+str(upper_lim)+";"+str(evaluating_float)+";-"+";-"+";PASS"+";-"+";PASS"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "2"):

				UIManager.SYNCGRID3(["UI","GRID3","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "3"):

				UIManager.SYNCGRID4(["UI","GRID4","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

		else:

			TestData.setContent(result_index[0], str(evaluating_float))
			TestData.setContent(result_index[1], "FAIL")
			TestData.setContent(result_index[2], test_id)

			if(grid_info == "min"):
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";"+str(upper_lim)+";"+str(evaluating_float)+";FAIL"+";-"+";FAIL"
			else:
				grid_message = test_id + ";"+str( int(kill_index) + 1 )+";"+str(lower_lim)+";-"+";"+str(upper_lim)+";"+str(evaluating_float)+";-"+";-"+";FAIL"+";-"+";FAIL"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID3(["UI","GRID3","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID4(["UI","GRID4","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			TestData.kill(kill_index)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#High level evaluation if a string is contained in a result
async def EVACSTR(line, UI):

	#0    1       2             3                        4                   5               6
	#Flow EVACSTR target_str    under_evaluation_str     write_result_index  grid_info       kill_index,test_ID
	#Flow EVACSTR pass          resultpass               0,0,0;0,1,0;0,2,0                   0,MASTER_1_FLASH

	try:

		target_str = TestData.getContent(line[2])

		result_index = TestData.getContent(line[4])
		result_index =  result_index.split(';')

		#grid_message = TestData.getContent(line[5])

		extra_info = TestData.getContent(line[6])
		extra_info = extra_info.split(',')
		test_id = extra_info[1]
		kill_index = extra_info[0]

		try:

			evaluating_str = TestData.getContent(line[3])

		except Exception as x:

			TestData.setContent(result_index[0], "N.O.K.")
			TestData.setContent(result_index[1], "FAIL")
			TestData.setContent(result_index[2], test_id)

			grid_message = test_id + ";"+str( int(kill_index) + 1 )+";-"+";-"+";-"+";-"+";-"+";-"+";FAIL"+";-"+";FAIL"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			TestData.kill(kill_index)

			return

		if(target_str in evaluating_str):

			TestData.setContent(result_index[0], "O.K.")
			TestData.setContent(result_index[1], "PASS")
			TestData.setContent(result_index[2], test_id)

			grid_message = test_id + ";"+str( int(kill_index) + 1 )+";-"+";-"+";-"+";-"+";-"+";-"+";PASS"+";-"+";PASS"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

		else:

			TestData.setContent(result_index[0], "N.O.K.")
			TestData.setContent(result_index[1], "FAIL")
			TestData.setContent(result_index[2], test_id)

			grid_message = test_id + ";"+str( int(kill_index) + 1 )+";-"+";-"+";-"+";-"+";-"+";-"+";FAIL"+";-"+";FAIL"

			if(kill_index == "0"):

				UIManager.SYNCGRID1(["UI","GRID1","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			elif(kill_index == "1"):

				UIManager.SYNCGRID2(["UI","GRID2","Add","const",grid_message,"-","-","UI_EX","-","-","-"],UI)

			TestData.kill(kill_index)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#JSON
async def JSON(line, UI):

	#0    1    2          3        4
	#Flow JSON Load       filename l,c,p
	#Load JSON filename to l,c,p

	#0    1    2   3      4     5
	#Flow JSON Get *l,c,p field l,c,p
	#Get JSON field from *l,c,p and save it at l,c,p
	#5 = 3['4']

	try:

		argument = line[2]

		match argument:

			case "Load":

				try:

					line3 = TestData.getContent(line[3])

					TestData.setContentNS(line[4], json.loads(line3))

					UI.addToLbox("Loaded JSON " + line[3] + " to " + line[4])

				except Exception as e:

					UI.addToLbox(str(e))
					UI.addToLbox("Exception loading JSON File, setting " + line[5] + " to FAIL")
					TestData.setContentNS(line[5], "FAIL")

				return

			case "Get":

				try:

					line3 = TestData.getContent(line[3])

				except Exception as e1:

					UI.addToLbox(str(e1))
					UI.addToLbox("Exception getting JSON from " + line[3] + " setting " + line[5] + "to FAIL")
					TestData.setContentNS(line[5], "FAIL")

					return


				line4 = TestData.getContent(line[4])

				try:

					TestData.setContentNS(line[5], line3[line4])

					UI.addToLbox(line[5] + " = " + line[3] + "['" + line4 + "']" + " = " + str(line3[line4]))

				except Exception as e2:

					UI.addToLbox(str(e2))
					UI.addToLbox("Exception getting key from JSON file, setting " + line[5] + " to FAIL.")
					TestData.setContentNS(line[5], "FAIL")


				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

async def RESET_TIMER(line, UI):

	#Flow RESET_TIMER

	TestData.ref_time = round(time.perf_counter())

async def ENABLE_TIMER(line, UI):

	#Flow ENABLE_TIMER

	TestData.update_time = True

async def DISABLE_TIMER(line, UI):

	#Flow DISABLE_TIMER

	TestData.update_time = False

async def START_TIME(line, UI):

	#0		1			2
	#Flow 	START_TIME 	l,c,p

	try:
		save_index = TestData.getContent(line[2])
		
		current_date = datetime.now()
		date_string = current_date.strftime("%Y%m%d_%H%M%S")

		TestData.setContent(save_index, date_string)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))


#Helpers

#Set TestData.pointer to label position - 1
def jump(target):

	for label in TestData.Labels:

		if(label["Label"] == target):

			TestData.pointer = int(label["index"]) - 1

def to_float(s):
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return float(int(s, 16))
    except ValueError:
        raise ValueError(f"Cannot convert {s!r} to float")

#end
