#Test table and data array initializations, these methods are NOT
#to be called by the test table execution phase, unless they are async

import asyncio
import datetime
import os

#Test Table
TestTable = None

#Test Table Labels
Labels = None

#Data array structure
#Number of lines
lines = None
#Number of columns
cols = None
#Number of Pages
pages = None
#Data
data = None

#Alive array
Alive = None

#Test Table pointer
pointer = None

#Flow variables
update_time = False
ref_time = 0.0
line_start = 0
line_end = 0
line_span = 0
Datecode = None
Extended_Datecode = None

log_flag = True

async def LOG_FLAG(line, UI):

	global log_flag

	if(line[2]=="ON"):

		print("SETTING FLAG ON")
		log_flag = True

	else:

		print("SETTING FLAG OFF")
		log_flag = False

#Increment the test table pointer by 1
def incPointer():

	global pointer

	pointer = pointer + 1

#Reset the test table pointer to the start of the execute region
def resetPointer():

	global pointer
	global TestTable

	for i in range(len(TestTable)):

		if(TestTable[i][0] == "<Exec>"):

			pointer = i + 1
			break

#Returns an list with 3 integer values corresponding to the index
def getIndex(s):

	indexes = s.split(',')

	int_indexes = []

	for i in range(len(indexes)):

		int_indexes.append(int(indexes[i]))

	return int_indexes

#Returns the contents of a data at a given index if the input has * as first character, ex: *1,0,1s. Else returns the input string.
def getContent(s):

	if(s[0] == '*'):

		return getData(s.replace("*",""))

	else:

		return s

#Sets the content of data at a given index, data[index] = content, NS = NOT STRING
def setContentNS(index, content):

	global data

	idx = getIndex(index)

	data[idx[0]][idx[1]][idx[2]] = content

#Sets the content of data at a given index, data[index] = content
def setContent(index, content):

	global data

	idx = getIndex(index)

	data[idx[0]][idx[1]][idx[2]] = str(content)

	#print(str(idx[0])+","+str(idx[1])+","+str(idx[2]) + " = " + data[idx[0]][idx[1]][idx[2]])

#Returns the contents of data at a given index l,c,p
def getData(s):

	global data

	idx = getIndex(s)

	return (data[idx[0]][idx[1]][idx[2]])

#Initializes the data array with a given l,c,p size
async def INITDATA(line, UI):

	global data

	global lines
	global cols
	global pages

	lines = line[2]
	cols = line[3]
	pages = line[4]

	data = [[[None for k in range(int(pages))] for j in range(int(cols))] for i in range(int(lines))]

	UI.addToTestPageLbox("Data initialized: " + lines + " lines, " + cols + " cols, " + pages + " pages.")

#Updates the Labels list
def updateLabels(line, UI):

	global TestTable
	global Labels
	global line_span
	global line_start
	global line_end

	start_idx = 0
	end_idx = 0

	Labels = []

	UI.addToTestPageLbox("Updating Labels..")

	for i in range(len(TestTable)):

		if(TestTable[i][1] == "LABEL"):

			UI.addToTestPageLbox("Adding " + str(i) + " : " + TestTable[i][2])

			Labels.append({
				"index": i,
				"Label": TestTable[i][2]
			})

			if(TestTable[i][2] == "START"):

				line_start = i

			elif(TestTable[i][2] == "END"):

				line_end = i

	line_span = line_end - line_start

	UI.addToTestPageLbox("Test Span: " + str(line_span))

#Initializes the Alive lists with a given size
def initAlive(line, UI):

	global Alive

	Alive = [0 for k in range(int(line[2]))]

	UI.addToTestPageLbox("Alive initialized with " + line[2] + " elements.")

#Sets all values on the Alive list to 1
async def STARTALIVE(line, UI):

	global Alive

	for i in range(len(Alive)):

		Alive[i] = 1

	UI.addToTestPageLbox("Everyone is alive!")

#Returns True if at least of indexes at Alive is 1, Returns False otherwise
def isAnyAlive(indexes):

	global Alive

	if(str(indexes) == '-'):

		return True

	idx = indexes.split(',')

	if(idx[0] == '-'):

		for i in range(1,len(idx)):

			if(Alive[int(idx[i])] == 0):

				return False

		return True

	for i in range(len(idx)):

		if(Alive[int(idx[i])] == 1):

			return True

	return False

#Sets the datacode and extended_datacode
async def SETDATACODES(line,UI):

	global Datecode
	global Extended_Datecode

	now = datetime.datetime.now()
	Datecode = str(now.year) + "y_" + str(now.month) + "m_" + str(now.day) + "d"
	Extended_Datecode = str(now.hour) + "h_" + str(now.minute) + "m_" + str(now.second) + "s"

	UI.addToLbox("Datecode: " + Datecode)
	UI.addToLbox("Extended Datecode: " + Extended_Datecode)

	idx = getIndex(line[2])
	idx1 = getIndex(line[3])
	data[idx[0]][idx[1]][idx[2]] = Datecode
	data[idx1[0]][idx1[1]][idx1[2]] = Extended_Datecode

#Sets one or more indexes at Alive to 0
def kill(arg):

	global Alive

	targets = arg.split(',')

	for target in targets:

		Alive[int(target)] = 0

		print("Killed " + target + "!")

#Sets one or more indexes at Alive to 0
async def AKILL(line, UI):

	#TestData akill targets

	try:

		global Alive

		targets = line[2].split(',')

		for target in targets:

			Alive[int(target)] = 0

			UI.addToLbox("Killed " + target + "!")

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Save testing LOG
async def SAVELOG(line, UI):

	#./home/Nikola/Desktop/Results/Datecode/Extended_Datecode/LOG_Barcode.txt

	global Datecode
	global Extended_Datecode

	dir = getContent(line[2])

	UI.addToLbox("Saving LOG at: " + dir)

	filename = dir

	'''
	isExist = os.path.exists(dir + Datecode + "/")

	if not isExist:

		os.mkdir(dir + Datecode)

	isExist = os.path.exists(dir + Datecode + "/" + Extended_Datecode)
	if not isExist:

		os.mkdir(dir + Datecode + "/" + Extended_Datecode)
	'''

	with open(filename, 'w') as f:

		log = UI.frames[0].getAllLbox()

		for line in log:

			f.write(line)

#Save testing DATA
async def SAVEDATA(line, UI):

	#./home/Nikola/Desktop/Results/Datecode/Extended_Datecode/DATA_Barcode.txt

	global Datecode
	global Extended_Datecode
	global lines
	global cols
	global pages

	dir = getContent(line[2])

	UI.addToLbox("Saving DATA at: " + dir)

	filename = dir

	'''
	isExist = os.path.exists(dir + Datecode + "/")

	if not isExist:

		os.mkdir(dir + Datecode)

	isExist = os.path.exists(dir + Datecode + "/" + Extended_Datecode)
	if not isExist:

		os.mkdir(dir + Datecode + "/" + Extended_Datecode)
	'''

	with open(filename, 'w') as f:

		for i in range(int(pages)):

			f.write("PAGE " + str(i) + "::\n")

			for j in range(int(lines)):

				if( (data[j][0][i] is None) and (data[j][1][i] is None) and (data[j][2][i] is None) ):

					continue

				f.write("[" + str(j) + ",0," + str(i) + "]: ")

				if( not( data[j][0][i] is None) ):

					try:

						f.write( str((data[j][0][i])) )

					except Exception as e1:

						UI.addToLbox("Exception writing data: " + str(e1))

				else:

					f.write("-")

				f.write(" \t\t|| ")

				f.write("[" + str(j) + ",1," + str(i) + "]: ")

				if( not( data[j][1][i] is None) ):

					try:

						f.write( str((data[j][1][i])) )

					except Exception as e2:

						UI.addToLbox("Exception writing data: " + str(e2))

				else:

					f.write("-")

				f.write(" \t\t|| ")

				f.write("[" + str(j) + ",2," + str(i) + "]: ")

				if( not( data[j][2][i] is None) ):

					try:

						f.write( (data[j][2][i]) )

					except Exception as e2:

						UI.addToLbox("Exception writing data: " + str(e2))

				else:

					f.write("-")

				f.write("\n")

#end
