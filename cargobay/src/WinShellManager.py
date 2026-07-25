#SHELL MANAGER FOR WINDOWS

import os
from multiprocessing import Process
import subprocess
import asyncio
import TestData
from threading import Timer

#Call a blocking process to execute a bash command and save standard output at data
async def BLOCK(line, UI):

	#0     1     2                       3           4           5
	#Shell BLOCK args                    l,c,p(out)  l,c,p(err)  exitcode
	#Shell BLOCK sh,testing.sh,arg1,arg2 0,0,3       1,0,3       2,0,3

	idx = TestData.getIndex(line[3])
	idxerr = TestData.getIndex(line[4])

	try:

		cmd = line[2].split(',')

		UI.addToLbox("Starting Subprocess bash script: " + line[2])

		ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		out,err = ret.communicate()

		if(line[5] != "-"):

			exitcode = ret.returncode
			TestData.setContent(line[5], exitcode)

		UI.addToLbox("Subprocess bash script: " + line[2] + " finished with exit code: " + str(ret.returncode))

		TestData.data[idx[0]][idx[1]][idx[2]] = out.decode('UTF-8')

		if(line[4] != "-"):

			TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = err.decode('UTF-8')


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Call a blocking process to execute a bash command and save standard output at data
async def BLOCKSH(line, UI):

	#0     1     2                       3           4           5         6
	#Shell BLOCK args                    l,c,p(out)  l,c,p(err)  exitcode  timeout
	#Shell BLOCK sh,testing.sh,arg1,arg2 0,0,3       1,0,3       2,0,3     2

	idx = TestData.getIndex(line[3])
	idxerr = TestData.getIndex(line[4])

	try:

		cmd = line[2].split(',')

		UI.addToLbox("Starting Subprocess bash script: " + line[2])

		ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

		out,err = ret.communicate()

		if(line[5] != "-"):

			exitcode = ret.returncode
			TestData.setContent(line[5], exitcode)

		UI.addToLbox("Subprocess bash script: " + line[2] + " finished with exit code: " + str(ret.returncode))

		TestData.data[idx[0]][idx[1]][idx[2]] = out.decode('UTF-8')

		if(line[4] != "-"):

			TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = err.decode('UTF-8')


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Call a blocking process to execute a bash command and save standard output at data
async def BLOCKSHT(line, UI):

	#0     1        2                       3           4           5         6
	#Shell BLOCKSHT args                    l,c,p(out)  l,c,p(err)  exitcode  timeout,timeout_handling_function
	#Shell BLOCKSHT sh,testing.sh,arg1,arg2 0,0,3       1,0,3       2,0,3     2,function

	idx = TestData.getIndex(line[3])
	idxerr = TestData.getIndex(line[4])

	timeout_info = line[6].split(',')

	ret = None

	print(globals()[timeout_info[1]])

	my_timer = Timer(int(timeout_info[0]), globals()[timeout_info[1]] )

	try:

		cmd = line[2].split(',')

		UI.addToLbox("Starting Subprocess bash script: " + line[2])

		ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

		my_timer.start()

		out,err = ret.communicate()

		print(out)
		print(err)

		if(line[5] != "-"):

			exitcode = ret.returncode
			TestData.setContent(line[5], exitcode)

		UI.addToLbox("Subprocess bash script: " + line[2] + " finished with exit code: " + str(ret.returncode))

		TestData.setContent(line[3], out.decode())

		if(line[4] != "-"):

			TestData.setContent(line[4], out.decode())


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

	finally:

		UI.addToLbox("Canceling timeout timer..")

		my_timer.cancel()

#Call a blocking process to execute a bash command and save standard output at data
async def BLOCKT(line, UI):

	#0     1        2                       3           4           5         6
	#Shell BLOCKSHT args                    l,c,p(out)  l,c,p(err)  exitcode  timeout,timeout_handling_function
	#Shell BLOCKSHT sh,testing.sh,arg1,arg2 0,0,3       1,0,3       2,0,3     2,function

	idx = TestData.getIndex(line[3])
	idxerr = TestData.getIndex(line[4])

	timeout_info = line[6].split(',')

	ret = None

	try:

		cmd = line[2].split(',')

		UI.addToLbox("Starting Subprocess bash script: " + line[2])

		ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		my_timer = Timer(int(timeout_info[0]), timeout_info[1])

		my_timer.start()

		out,err = ret.communicate()

		if(line[5] != "-"):

			exitcode = ret.returncode
			TestData.setContent(line[5], exitcode)

		UI.addToLbox("Subprocess bash script: " + line[2] + " finished with exit code: " + str(ret.returncode))

		TestData.data[idx[0]][idx[1]][idx[2]] = out.decode('UTF-8')

		if(line[4] != "-"):

			TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = err.decode('UTF-8')


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

	finally:

		UI.addToLbox("Canceling timeout timer..")

		my_timer.cancel()

#Call a blocking process to execute a bash command and save standard output at data
async def BLOCK2(line, UI):

	#0     1     2                       3           4           5
	#Shell BLOCK args                    l,c,p(out)  l,c,p(err)  exitcode
	#Shell BLOCK sh,testing.sh,arg1,arg2 0,0,3       1,0,3       2,0,3

	idx = TestData.getIndex(line[3])
	idxerr = TestData.getIndex(line[4])

	try:

		cmd = line[2].split(';')

		UI.addToLbox("Starting Subprocess bash script: " + line[2])

		ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		out,err = ret.communicate()

		if(line[5] != "-"):

			exitcode = ret.returncode
			TestData.setContent(line[5], exitcode)

		UI.addToLbox("Subprocess bash script: " + line[2] + " finished with exit code: " + str(ret.returncode))

		TestData.data[idx[0]][idx[1]][idx[2]] = out.decode('UTF-8')

		if(line[4] != "-"):

			TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = err.decode('UTF-8')


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Call a nonblocking proccess to execute a bash command and save standard output at data
async def NONBLOCK(line, UI):

	#0     1          2                                                      3		     4
	#Shell NONBLOCK   cmd_args                                               save_stdout save_err
	#Shell NONBLOCK   gnome-terminal,--wait,--,bash,example.sh,arg1,arg2     0,0,0       1,0,0

	cmd = line[2].split(';')

	for i in range(len(cmd)):

		cmd[i] = TestData.getContent(cmd[i])

		UI.addToLbox(str(cmd[i]))

	try:

		UI.addToLbox("Starting Subprocess: " + line[2])

		proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

		stdout, stderr = await proc.communicate()

		UI.addToLbox("Subprocess: " + line[2] + " finished with exit code: " + str(proc.returncode))

		idx = TestData.getIndex(line[3])
		idxerr = TestData.getIndex(line[4])

		TestData.data[idx[0]][idx[1]][idx[2]] = stdout.decode()
		TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = stderr.decode()

		#print("STDOUT: " + TestData.data[idx[0]][idx[1]][idx[2]])

		#if( not(str(proc.returncode) == "0") ):

		#	raise Exception("Process return code failed: " + str(proc.returncode))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Call a nonblocking proccess to execute a bash command and save standard output at data
async def ASYNC(line, UI):

	#0     1          2                                                      3		     4        5             6
	#Shell ASYNC   cmd_args                                               save_stdout save_err save_errcode  pre_delay
	#Shell ASYNC   gnome-terminal,--wait,--,bash,example.sh,arg1,arg2     0,0,0       1,0,0	  2,0,0         1

	cmd = line[2].split(';')

	for i in range(len(cmd)):

		cmd[i] = TestData.getContent(cmd[i])

	try:

		if(line[6] != '-'):

			UI.addToLbox("Pre Delay: " + line[6] + " seconds.")

			await asyncio.sleep(float(line[6]))

		UI.addToLbox("Starting Subprocess: " + line[2])

		proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

		stdout, stderr = await proc.communicate()

		UI.addToLbox("Subprocess: " + line[2] + " finished with exit code: " + str(proc.returncode))

		idxout = TestData.getIndex(line[3])
		idxerr = TestData.getIndex(line[4])
		idxec = TestData.getIndex(line[5])


		TestData.data[idxout[0]][idxout[1]][idxout[2]] = stdout.decode()
		TestData.data[idxerr[0]][idxerr[1]][idxerr[2]] = stderr.decode()
		TestData.data[idxec[0]][idxec[1]][idxec[2]] = str(proc.returncode)

		#print("STDOUT: " + TestData.data[idx[0]][idx[1]][idx[2]])

		#if( not(str(proc.returncode) == "0") ):

		#	raise Exception("Process return code failed: " + str(proc.returncode))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

def killadb():

	print("killing adb..")

	os.system("pkill adb")

def killnetcat():

	print("killing netcat..")

	os.system("pkill netcat")

def killcurl():

	print("killing curl..")

	os.system("pkill curl")

def killipe():

	print("killing ipe..")

	os.system("taskkill /IM ipecmdboost.exe /F")
	os.system("taskkill /IM java.exe /F")


#end
