#UI MANAGER

import TestData
import asyncio
import tkinter as tk
from tkinter import ttk

#Edit the elements of GRID1.
def SYNCGRID1(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID1 Add    const  "data"
	#UI GRID1 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID1 Add	 var    *l,c,p

			#l,c,p contains a list ['ID','Device','min', ...]

	#UI GRID1 Clear

	#UI GRID1 Place  relx   rely   relwidth   relheight

	#UI GRID1 Unplace

	try:

		tree_size = len(UI.frames[0].Tree["columns"])

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + str(line[4]) + " to DGRID1.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				elif(line[3] == "var"):

					_data = TestData.getContent(line[4])

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				return

			case "Clear":

				UI.addToLbox("Clearing DGRID1.")

				UI.frames[0].Tree.delete(*UI.frames[0].Tree.get_children())
				UI.frames[0].DGRID1_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID1..")

				UI.frames[0].Tree.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID1.")

				UI.frames[0].Tree.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID1.
async def GRID1(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID1 Add    const  "data"
	#UI GRID1 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID1 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID1 Clear

	#UI GRID1 Place  relx   rely   relwidth   relheight

	#UI GRID1 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + str(line[4]) + " to DGRID1.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				elif(line[3] == "var"):

					_data = TestData.getContent(line[4])

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				return

			case "Clear":

				UI.addToLbox("Clearing DGRID1.")

				UI.frames[0].Tree.delete(*UI.frames[0].Tree.get_children())
				UI.frames[0].DGRID1_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID1..")

				UI.frames[0].Tree.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID1.")

				UI.frames[0].Tree.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID2.
def SYNCGRID2(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID2 Add    const  "data"
	#UI GRID2 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID2 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID2 Clear

	#UI GRID2 Place  relx   rely   relwidth   relheight

	#UI GRID2 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + str(line[4]) + " to DGRID2.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)

				elif(line[3] == "var"):

					_data = TestData.getContent(line[4])

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)
				return

			case "Clear":

				UI.addToLbox("Clearing DGRID2.")

				UI.frames[0].Tree2.delete(*UI.frames[0].Tree2.get_children())
				UI.frames[0].DGRID2_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID2.")

				UI.frames[0].Tree2.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID2.")

				UI.frames[0].Tree2.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID2.
async def GRID2(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID2 Add    const  "data"
	#UI GRID2 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID2 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID2 Clear

	#UI GRID2 Place  relx   rely   relwidth   relheight

	#UI GRID2 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + str(line[4]) + " to DGRID2.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)

				elif(line[3] == "var"):

					_data = TestData.getContent(line[4])

					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = _data[0:len(_data)-2], tag=_data[len(_data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)
				return

			case "Clear":

				UI.addToLbox("Clearing DGRID2.")

				UI.frames[0].Tree2.delete(*UI.frames[0].Tree2.get_children())
				UI.frames[0].DGRID2_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID2.")

				UI.frames[0].Tree2.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID2.")

				UI.frames[0].Tree2.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Config GRID1, to be used at <Config> section only.
def GRID1_CONFIG(line, UI):

	#0  1            2             3      4      5          6
	#UI GRID1_CONFIG Place         relx   rely   relwidth   relheight
	#UI GRID1_CONFIG Unplace

	#UI GRID1_CONFIG Add_Columns   info # info example: Test ID,Device,Min.,Typ.,Max.,Response,Expected Response,Additional Info,Result,Comment
	#UI GRID1_CONFIG Edit_Column   info # info example: Test ID,100,0
	#UI GRID1_CONFIG Edit_Heading  info # info example: Test ID,Test ID Name
	#UI GRID1_CONFIG Tag_Config    info # info example: OK,#00e600

	try:

		argument =  line[2]

		match argument:

			case "Add_Columns":

				info = line[3].split(',')

				#UI.frames[0].Tree["columns"] = (info[0], info[1], info[2], info[3], info[4], info[5], info[6], info[7], info[8], info[9])

				UI.frames[0].Tree["columns"] = info

				return

			case "Edit_Column":

				info = line[3].split(',')

				UI.frames[0].Tree.column(info[0], width = int(info[1]), minwidth = int(info[2]), stretch=tk.YES)

				return

			case "Edit_Heading":

				info = line[3].split(',')

				UI.frames[0].Tree.heading(info[0], text=info[1], ancho=tk.W)

				return

			case "Tag_Config":

				info = line[3].split(',')

				UI.frames[0].Tree.tag_configure(info[0], background=info[1])

				return

			case "Unplace":

				UI.frames[0].Tree.place_forget()

				return

			case "Place":

				UI.frames[0].Tree.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Config GRID2, to be used at <Config> section only.
def GRID2_CONFIG(line, UI):

	#0  1            2             3      4      5          6
	#UI GRID2_CONFIG Place         relx   rely   relwidth   relheight
	#UI GRID2_CONFIG Unplace

	#UI GRID2_CONFIG Add_Columns   info # info example: Test ID,Device,Min.,Typ.,Max.,Response,Expected Response,Additional Info,Result,Comment
	#UI GRID2_CONFIG Edit_Column   info # info example: Test ID,100,0
	#UI GRID2_CONFIG Edit_Heading  info # info example: Test ID,Test ID Name
	#UI GRID2_CONFIG Tag_Config    info # info example: OK,#00e600

	try:

		argument =  line[2]

		match argument:

			case "Add_Columns":

				info = line[3].split(',')

				#UI.frames[0].Tree2["columns"] = (info[0], info[1], info[2], info[3], info[4], info[5], info[6], info[7], info[8], info[9])

				UI.frames[0].Tree2["columns"] = info

				return

			case "Edit_Column":

				info = line[3].split(',')

				UI.frames[0].Tree2.column(info[0], width = int(info[1]), minwidth = int(info[2]), stretch=tk.YES)

				return

			case "Edit_Heading":

				info = line[3].split(',')

				UI.frames[0].Tree2.heading(info[0], text=info[1], ancho=tk.W)

				return

			case "Tag_Config":

				info = line[3].split(',')

				UI.frames[0].Tree2.tag_configure(info[0], background=info[1])

				return

			case "Unplace":

				UI.frames[0].Tree2.place_forget()

				return

			case "Place":

				UI.frames[0].Tree2.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return


	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the STATUS
async def STATUS(line, UI):

	#UI STATUS Clear
	#UI STATUS Set status

	try:

		argument = line[2]

		match argument:

			case "Clear":

				UI.frames[0].status_label.configure(text = "")

				return

			case "Set":

				line3 = TestData.getContent(line[3])

				UI.frames[0].status_label.configure(text = line3)

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

async def WID(line, UI):

	try:

		worker = str(UI.frames[0].id_entry.get())

		if(worker == ""):

			raise Exception("INVALID WORKER")

		TestData.setContent("36,1,24", worker)

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the BCODE1 ENTRY
async def BCODE1(line, UI):

	#UI BCODE1 Clear
	#UI BCODE1 Set barcode

	try:

		argument = TestData.getContent(line[2])
		barcode = TestData.getContent(line[3])

		match argument:

			case "Clear":

				UI.frames[0].barcode_entry.delete(0,tk.END)

				return

			case "Set":

				UI.frames[0].barcode_entry.delete(0,tk.END)
				UI.frames[0].barcode_entry.insert(0,barcode)

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the BCODE2 ENTRY
async def BCODE2(line, UI):

	#UI BCODE1 Clear
	#UI BCODE1 Set barcode

	try:

		argument = TestData.getContent(line[2])
		barcode = TestData.getContent(line[3])

		match argument:

			case "Clear":

				UI.frames[0].barcode_entry2.delete(0,tk.END)

				return

			case "Set":

				UI.frames[0].barcode_entry2.delete(0,tk.END)
				UI.frames[0].barcode_entry2.insert(0,barcode)

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

async def PBAR(line, UI):

	#UI PBAR values

	try:

		UI.frames[0].setPBar(float(line[2]))

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))
	
async def RESETPBARCOLOR(line, UI):

	UI.frames[0].progressbar.configure(progress_color = "#689ed7")


#Edit the ListBox
async def LBOX(line, UI):

	#UI LBOX Clear

	try:

		argument = line[2]

		match argument:

			case "Clear":

				UI.frames[0].clearLbox()
				UI.addToLbox("Messages cleared!")

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

def CMONITOR(line, UI):

	#UI CMONITOR Messages color kill_index

	try:

		kill_index = TestData.getContent(line[4])

		if(kill_index == "0"):

			UI.frames[0].CMONITOR1["bg"] = TestData.getContent(line[3])
			UI.frames[0].CMONITOR1["text"] = line[2]

		elif(kill_index == "1"):

			UI.frames[0].CMONITOR2["bg"] = TestData.getContent(line[3])
			UI.frames[0].CMONITOR2["text"] = line[2]


	except Exception as e:

		raise Exception("CMONITOR" + "::" + str(e))

#DEPRECATD METHODS
'''
#Edit the elements of GRID1. DEPRECATED
def SYNCGRID1_D(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID1 Add    const  "data"
	#UI GRID1 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID1 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID1 Clear

	#UI GRID1 Place  relx   rely   relwidth   relheight

	#UI GRID1 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + line[4] + " to DGRID1.")

				if(line[3] == "const"):

					#print(line[4])

					_data = line[4].split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

						if '*' in data[i]:

							data[i] = data[i].replace('*','')

							idx = TestData.getIndex(data[i])

							data[i] = str(TestData.data[idx[0]][idx[1]][idx[2]])

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					print(split_data)

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				elif(line[3] == "var"):

					#idx = TestData.getIndex(line[4])
					#_data = str(TestData.data[idx[0]][idx[1]][idx[2]]).split(';')

					_data = TestData.getContent(line[4]).split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				return

			case "Clear":

				UI.addToLbox("Clearing DGRID1.")

				UI.frames[0].Tree.delete(*UI.frames[0].Tree.get_children())
				UI.frames[0].DGRID1_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID1..")

				UI.frames[0].Tree.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID1.")

				UI.frames[0].Tree.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID1. DEPRECATED
async def GRID1_D(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID1 Add    const  "data"
	#UI GRID1 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID1 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID1 Clear

	#UI GRID1 Place  relx   rely   relwidth   relheight

	#UI GRID1 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + line[4] + " to DGRID1.")

				if(line[3] == "const"):

					print(line[4])

					_data = line[4].split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

						if '*' in data[i]:

							data[i] = data[i].replace('*','')

							idx = TestData.getIndex(data[i])

							data[i] = str(TestData.data[idx[0]][idx[1]][idx[2]])

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					print(split_data)

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				elif(line[3] == "var"):

					#idx = TestData.getIndex(line[4])
					#_data = str(TestData.data[idx[0]][idx[1]][idx[2]]).split(';')

					_data = TestData.getContent(line[4]).split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree.insert(parent='',index='end',iid=UI.frames[0].DGRID1_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID1_iid += 1
					UI.frames[0].Tree.yview_moveto(1)

				return

			case "Clear":

				UI.addToLbox("Clearing DGRID1.")

				UI.frames[0].Tree.delete(*UI.frames[0].Tree.get_children())
				UI.frames[0].DGRID1_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID1..")

				UI.frames[0].Tree.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID1.")

				UI.frames[0].Tree.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID2. DEPRECATD
def SYNCGRID2_D(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID2 Add    const  "data"
	#UI GRID2 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID2 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID2 Clear

	#UI GRID2 Place  relx   rely   relwidth   relheight

	#UI GRID2 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + line[4] + " to DGRID2.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

						if '*' in data[i]:

							data[i] = data[i].replace('*','')

							idx = TestData.getIndex(data[i])

							data[i] = str(TestData.data[idx[0]][idx[1]][idx[2]])

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)

				elif(line[3] == "var"):

					#idx = TestData.getIndex(line[4])
					#_data = str(TestData.data[idx[0]][idx[1]][idx[2]]).split(';')

					_data = TestData.getContent(line[4]).split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)
				return

			case "Clear":

				UI.addToLbox("Clearing DGRID2.")

				UI.frames[0].Tree2.delete(*UI.frames[0].Tree2.get_children())
				UI.frames[0].DGRID2_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID2.")

				UI.frames[0].Tree2.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID2.")

				UI.frames[0].Tree2.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))

#Edit the elements of GRID2. DEPRECATED
async def GRID2_D(line,UI):


	#0  1     2      3      4      5          6
	#UI GRID2 Add    const  "data"
	#UI GRID2 Add    const  ID,Device1,min,typ,max,-,-,-,*1,0,0,comment

			#To indicate data stored value, use &

	#UI GRID2 Add	 var    *l,c,p

			#l,c,p contains a string "ID,Device,etc"

	#UI GRID2 Clear

	#UI GRID2 Place  relx   rely   relwidth   relheight

	#UI GRID2 Unplace

	try:

		argument = line[2]

		match argument:

			case "Add":

				UI.addToLbox("Adding " + line[4] + " to DGRID2.")

				if(line[3] == "const"):

					_data = line[4].split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

						if '*' in data[i]:

							data[i] = data[i].replace('*','')

							idx = TestData.getIndex(data[i])

							data[i] = str(TestData.data[idx[0]][idx[1]][idx[2]])

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)

				elif(line[3] == "var"):

					#idx = TestData.getIndex(line[4])
					#_data = str(TestData.data[idx[0]][idx[1]][idx[2]]).split(';')

					_data = TestData.getContent(line[4]).split(';')

					data = ['-']*11

					data[10] = _data[len(_data) - 1]

					for i in range(len(_data) - 1):

						data[i] = _data[i]

					split_data = []

					for i in range(len(data) - 1):

						split_data.append(data[i])

					#UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9]), tag=data[10])
					UI.frames[0].Tree2.insert(parent='',index='end',iid=UI.frames[0].DGRID2_iid, text = "parent", values = split_data, tag=data[len(data) - 1])
					UI.frames[0].DGRID2_iid += 1
					UI.frames[0].Tree2.yview_moveto(1)
				return

			case "Clear":

				UI.addToLbox("Clearing DGRID2.")

				UI.frames[0].Tree2.delete(*UI.frames[0].Tree2.get_children())
				UI.frames[0].DGRID2_iid = 0

				return

			case "Place":

				UI.addToLbox("Placing DGRID2.")

				UI.frames[0].Tree2.place(relx = float(line[3]), rely=float(line[4]), relwidth=float(line[5]), relheight=float(line[6]))

				return

			case "Unplace":

				UI.addToLbox("Unplacing DGRID2.")

				UI.frames[0].Tree2.place_forget()

				return

			case "default":

				print("Invalid argument!")

				return

	except Exception as e:

		raise Exception(line[7] + "::" + str(e))
'''

#end
