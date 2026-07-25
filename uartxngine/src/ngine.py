#!/usr/bin/env python3

import time
import tkinter as tk
from tkinter import ttk
import customtkinter
from PIL import Image,ImageTk
from os import listdir, remove
from os.path import isfile, join, exists
import threading
import asyncio
import concurrent.futures
from multiprocessing import Process, active_children
import os
from pandas_ods_reader import read_ods
import pandas as pd
from pyexcel_ods import save_data
from collections import OrderedDict
import math

import TestData

globals()["TestData"] = __import__("TestData")
loop_flag = False
update_UI = False


#Test table class
class TestTable():

	def __init__(self, controller):
		self.controller = controller

	def odsTableToTxt(self, base_path):
		df = read_ods(base_path, 1)
		print(df)
		vals = df.values.tolist()
		txtpath = base_path.replace(".ods", ".txt")
		with open(txtpath, 'w') as f:
			for i in range(len(vals)):
				line = vals[i]
				for word in line:
					if (word is None):
						# print("nOnE", end=" ")
						f.write("-$")
						continue
					word = str(word)
					if (word == "nan"):
						# print("nAn", end=" ")
						f.write("-$")
						continue
					# print(word, end=" ")
					f.write(word + '$')
				# print(" ")
				f.write('\n')

	def saveTableOds(self):

		columns = ["C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"]
		# Convert the list of lists to a DataFrame for easier manipulation if necessary
		df = pd.DataFrame(TestData.TestTable, columns=columns)

		# Convert DataFrame back to list of lists to prepare for saving in ODS format
		data_dict = OrderedDict()
		data_dict["Sheet 1"] = [df.columns.tolist()] + df.values.tolist()

		# Save the data to an ODS file
		save_data("output.ods", data_dict)

	def loadTableInfoOds(self):

		self.controller.Tree.delete(*self.controller.Tree.get_children())
		path = "TestTables/" + self.controller.cbox.get()

		df = read_ods(path, 1)
		print(df)
		vals = df.values.tolist()

		idx = 0
		TestData.TestTable = []
		for i in range(len(vals)):
			line = vals[i]
			words = []
			for word in line:
				if (word is None):
					words.append("-")
					continue
				word = str(word)
				if (word == "nan"):
					words.append("-")
					continue
				words.append(word)

			if (len(words) < 10):
				for i in range(10 - len(words)):
					words.append("-")

			if (len(words) < 12):
				self.controller.Tree.insert(parent='', index='end', iid=idx, text="parent", values=(
				str(idx), words[0], words[1], words[2], words[3], words[4], words[5], words[6], words[7], words[8],
				words[9].replace("\n", "")), tag=words[9])
			else:
				self.controller.Tree.insert(parent='', index='end', iid=idx, text="parent", values=(
				words[0], words[1], words[2], words[3], words[4], words[5], words[6], words[7], words[8], words[9],
				words[10].replace("\n", "")), tag=words[10])

			TestData.TestTable.append(words)
			idx = idx + 1

		self.loadModules()
		self.loadConfig()

		print("loadTableInfoOds Completed.")

	def loadTableInfo(self):
		self.controller.Tree.delete(*self.controller.Tree.get_children())

		path = "TestTables/" + self.controller.cbox.get()
		#If selected table is a .ods file, generate a .txt file for it
		if(".ods" in path):
			self.odsTableToTxt(path)
			path = path.replace(".ods", ".txt")

		TestData.TestTable = []
		file_text = open(path, 'r')

		print("Reading file: " + path)
		lines = file_text.readlines()
		idx = 0
		for line in lines:

			words = line.split('$')
			if(len(words)<10):
				for i in range(10-len(words)):
					words.append("-")

			if(len(words)<12):
				self.controller.Tree.insert(parent='',index='end',iid=idx, text = "parent", values = (str(idx), words[0], words[1], words[2], words[3], words[4], words[5], words[6], words[7], words[8], words[9].replace("\n","")), tag=words[9])
			else:
				self.controller.Tree.insert(parent='',index='end',iid=idx, text = "parent", values = (words[0], words[1], words[2], words[3], words[4], words[5], words[6], words[7], words[8], words[9], words[10].replace("\n","")), tag=words[10])

			TestData.TestTable.append(words)
			idx = idx + 1

		self.loadModules()
		self.loadConfig()
		print("loadTableInfo Completed.")

	def saveTableInfo(self):

		if(exists("TestTables/" + self.controller.entry.get())):
			remove("TestTables/" + self.controller.entry.get())
		file = open("TestTables/" + self.controller.entry.get(), 'a')
		for line in self.controller.Tree.get_children():
			l = ""
			first_value = True
			for value in self.controller.Tree.item(line)['values']:
				if(first_value):
					first_value = False
					continue
				l = l + str(value) + "$"
			file.write(l + "\n")
		file.close()

	def loadModules(self):

		inside_modules = False
		for line in TestData.TestTable:

			print(line)

			if(line[0] == "<Modules/>"):
				inside_modules = False
				break
			elif(line[0] == "<Modules>"):
				inside_modules = True
				continue
			if(inside_modules == True):
				globals()[line[0]] = __import__(line[1])
				self.controller.controller.frames[0].addToLbox("Loaded module " +  str(line[1]) + " to var " + str(line[0]))
				print("Loaded module " +  str(line[1]) + " to var " + str(line[0]))

	def loadConfig(self):

		try:
			inside_config = False
			for line in TestData.TestTable:
				if(line[0] == "<Config/>"):
					inside_config = False
					break
				elif(line[0] == "<Config>"):
					inside_config = True
					continue
				if(inside_config == True):
					method_to_call = getattr(globals()[str(line[0])], str(line[1]))
					method_to_call(line, self.controller.controller)

			self.controller.controller.frames[0].PlayButton.configure(state = "normal")
			self.controller.controller.frames[0].status_label.configure(text = "Config Loaded")
			self.controller.controller.frames[0].status_label.configure(fg_color = "#62AF75")

		except Exception as e:

			self.controller.controller.frames[0].addToLbox(str(e))
			self.controller.controller.frames[0].status_label.configure(text = "Config Fail")
			self.controller.controller.frames[0].status_label.configure(fg_color = "#810D0D")
			self.controller.controller.frames[0].PlayButton.configure(state = "disabled")

#Testing loop class
class Loop():

	def __init__(self, UI):
		self.UI = UI

	async def flowManager(self):
		global loop_flag
		loop_flag = True
		while(loop_flag == True):
			await asyncio.sleep(.5)
			if(self.UI.frames[0].order == "run"):
				self.UI.clearLbox()
				await self.Go()
		print("flowManager died.")

	async def Go(self):
		global updatePeriod
		#updatePeriod = -1
		self.UI.frames[0].state = "running"
		self.UI.frames[0].setStop()
		try:
			TestData.resetPointer()
		except Exception as e:
			self.UI.addToTestPageLbox("Oops! Something went wrong. Did you load a test table?")

		self.UI.addToTestPageLbox("Execution has started.")
		while(self.UI.frames[0].order == "run"):
			await asyncio.sleep(0)
			if(TestData.update_time):
				self.UI.frames[0].time_label.configure(text = str(round(time.perf_counter()) - TestData.ref_time) + "(s)")
				progress =  (float(TestData.pointer) - float( TestData.line_start ) ) / (float(TestData.line_span))
				#self.UI.frames[0].percentage_label["text"] = str(progress) + "%"
				if(progress > 0):
					self.UI.frames[0].setPBar(progress)

			try:
				module = TestData.TestTable[TestData.pointer][0]
				currentline =  TestData.TestTable[TestData.pointer]
				print("Current Line: ")
				for word in currentline:
					print(word + " ", end = "")
				print("")
				#await asyncio.sleep(0.1)
				if(currentline[0] == '-'):
					TestData.incPointer()
					continue

				if(not(TestData.isAnyAlive(currentline[8]))):
					TestData.incPointer()
					self.UI.addToTestPageLbox(str(TestData.pointer) + "- " + currentline[8] + " is NOT alive!")
					continue

				if(currentline[0] == "<ParallelTask>"):
					self.UI.addToTestPageLbox(str(TestData.pointer) + "- Starting Parallel Task..")
					#tasks = currentline[1].split(",")
					_pointer = TestData.pointer + 1
					_currentline = TestData.TestTable[_pointer]
					tasks = []
					task_counter = 0
					while( not(_currentline[0] == "<ParallelTask/>") ):
						if(not(TestData.isAnyAlive(_currentline[8]))):
							self.UI.addToTestPageLbox(str(_pointer) + "- " + _currentline[8] + " is NOT alive!")
						else:
							self.UI.addToTestPageLbox(str(_pointer) + "- " + "Adding task: " + _currentline[0] + " " + _currentline[1])
							method_to_call = getattr(globals()[str(_currentline[0])], str(_currentline[1]) )
							tasks.append(method_to_call(_currentline, self.UI))

						task_counter = task_counter + 1
						_pointer = _pointer + 1
						_currentline = TestData.TestTable[_pointer]

					all_groups = await asyncio.gather(*[tasks[i] for i in range(len(tasks))])
					TestData.pointer = TestData.pointer + task_counter + 1

				else:
					method_to_call = getattr(globals()[str(currentline[0])], str(currentline[1]) )
					await method_to_call(currentline, self.UI)

				TestData.incPointer()

			except Exception as e:

				self.UI.addToTestPageLbox(str(TestData.pointer) + "- Exception: " + str(e))
				ex_args = str(e).split("::")
				if(len(ex_args) < 2):
					break
				ex_label = ex_args[0]
				if(ex_label == "-"):
					ex_label = "STD_EX"
				self.UI.addToTestPageLbox(str(TestData.pointer) + "- " + "Jumping to " + str(ex_label))
				for label in TestData.Labels:
					if(label["Label"] == ex_label):
						TestData.pointer = int(label["index"])

		self.UI.frames[0].order = "stop"
		self.UI.frames[0].state = "idle"
		self.UI.frames[0].setRun()
		self.UI.addToTestPageLbox("Execution has ended.")
		#updatePeriod = 0.016

	async def ParallelTask(self, startlabel):

		counter = 0

		while(counter < 2):

			await asyncio.sleep(1)

			print(startlabel)

			counter = counter + 1



	def End(self):

		self.running_flag = False

#UI Class
class UI(tk.Tk):
	
	def __init__(self, *args, **kwargs):
		tk.Tk.__init__(self, *args, **kwargs)
		tk.Tk.wm_title(self, "[Uartrónica] - Functional Test")
		#self.attributes('-type','dock')
		self.attributes('-fullscreen', True)
		#self.state('withdrawn')
		container = tk.Frame(self)
		container.pack(side="top", fill="both", expand=True)
		container.grid_rowconfigure(0, weight=1)
		container.grid_columnconfigure(0, weight=1)
		self.frames = []
		self.frames.append(TestPage(container, self))
		self.frames[0].grid(row=0, column=0, sticky="nsew")
		self.frames.append(TablePage(container, self))
		self.frames[1].grid(row=0, column=0, sticky="nsew")
		self.show_frame(0)
		#0 - TestPage
		#1 - TablePage

	def show_frame(self, cont):
		frame = self.frames[cont]
		frame.tkraise()
		
	def addToTestPageLbox(self, message):
		self.frames[0].addToLbox(message)
		
	def addToLbox(self, message):
		if(not( str(TestData.pointer) == "None") ):
			self.frames[0].addToLbox(str(TestData.pointer) + "- " + message)
		else:
			self.frames[0].addToLbox(message)
			
	def clearLbox(self):
		self.frames[0].clearLbox()

#UI sub class, testing page
class TestPage(tk.Frame):

	def __init__(self, parent, controller):
		tk.Frame.__init__(self, parent)
		self.next_lbox_index = 0

		bgcolor = "#181818"

		self.canvas = tk.Canvas(self, height=1080, width=1920, bg='#FFFFFF')
		self.canvas.pack()

		status_frame = tk.Frame(self, bg='#FFFFFF', bd=2)
		status_frame.place(relx=0.155, rely=0.01, relwidth=0.3, relheight=0.3, anchor='n')

		self.status_label = customtkinter.CTkLabel(status_frame, text="Info", font=("Consolas", 54), bg_color='white', fg_color=bgcolor, text_color = 'white', corner_radius = 4)
		self.status_label.place( relx = 0.00, rely = 0.00, relwidth=1, relheight=1)

		buttons_frame = tk.Frame(self, bg='#FFFFFF', bd=2)
		buttons_frame.place(relx=0.155, rely=0.31, relwidth=0.3, relheight=0.15, anchor='n')

		table_img = ImageTk.PhotoImage(Image.open("Assets/table.png").resize((96,96), Image.Resampling.LANCZOS))
		self.TableButton = customtkinter.CTkButton(buttons_frame, image = table_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 4, text = "", command = lambda: self.goTable(controller))
		self.TableButton.place(relx = 0.00, rely = 0.00, relwidth = 0.3, relheight= 1)

		self.run_img = ImageTk.PhotoImage(Image.open("Assets/play.png").resize((96,96), Image.Resampling.LANCZOS))
		self.stop_img = ImageTk.PhotoImage(Image.open("Assets/stop.png").resize((96,96), Image.Resampling.LANCZOS))
		self.PlayButton = customtkinter.CTkButton(buttons_frame, image = self.run_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 4, text = "", command = lambda: self.StartStop(controller))
		self.PlayButton.place(relx = 0.305, rely = 0.00, relwidth = 0.695, relheight= 1)

		messages_frame = tk.Frame(self, bg='#FFFFFF', bd=2)
		messages_frame.place(relx=0.155, rely=0.46, relwidth=0.3, relheight=0.53, anchor='n')

		self.lbox = customtkinter.CTkTextbox(messages_frame, fg_color = bgcolor, text_color = 'white', font=("Consolas", 16), corner_radius = 4, wrap='none', scrollbar_button_color = 'white')
		self.lbox.place(relx = 0.00, rely = 0.00, relwidth = 1, relheight = 1)

		self.info_frame = tk.Frame(self, bg='#FFFFFF', bd=2)
		self.info_frame.place(relx=0.6525, rely=0.01, relwidth=0.685, relheight=0.1, anchor='n')

		in_img = ImageTk.PhotoImage(Image.open("Assets/uartx.png").resize((110,110), Image.Resampling.LANCZOS))
		self.INButton = customtkinter.CTkButton(self.info_frame, image = in_img, text = "", fg_color = bgcolor)
		self.INButton.place(relx = 0.00, rely = 0.00, relwidth = 0.1, relheight= 1)

		self.barcode_entry = customtkinter.CTkEntry(self.info_frame, font=("Consolas", 20), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.barcode_entry.place(relx=0.16, rely=0.0, relwidth=0.3, relheight=0.5)
		barcode_img = ImageTk.PhotoImage(Image.open("Assets/barcode_icon.png").resize((50,50), Image.Resampling.LANCZOS))
		self.BarcodeButton = customtkinter.CTkButton(self.info_frame, image = barcode_img, text = "", fg_color = bgcolor , corner_radius = 0, border_width = 0)
		self.BarcodeButton.place(relx = 0.11, rely = 0.00, relwidth = 0.05, relheight= 0.5)

		self.barcode_entry2 = customtkinter.CTkEntry(self.info_frame, font=("Consolas", 20), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.barcode_entry2.place(relx = 0.16, rely = 0.51, relwidth = 0.3, relheight= 0.49)

		self.time_label = customtkinter.CTkLabel(self.info_frame, text="0(s)", font=("Consolas", 20), text_color = 'white', bg_color='white', fg_color=bgcolor, corner_radius = 0)
		self.time_label.place(relx=0.51, rely=0.0, relwidth=0.1,relheight=0.5)
		
		time_img = ImageTk.PhotoImage(Image.open("Assets/time.png").resize((50,50), Image.Resampling.LANCZOS))
		
		self.TimeButton = customtkinter.CTkButton(self.info_frame, image = time_img, text = "", fg_color = bgcolor, corner_radius = 0, border_width = 0)
		self.TimeButton.place(relx = 0.46, rely = 0.00, relwidth = 0.05, relheight= 0.5)

		self.percentage_label = tk.Label(self.info_frame, text="0%", font=("Consolas", 16), bg=bgcolor, fg='white')
		self.progressbar = customtkinter.CTkProgressBar(self.info_frame, corner_radius = 0, fg_color = '#E9E9E9', progress_color = "#689ed7", mode = 'indeterminate', indeterminate_speed = 1)
		self.progressbar.place(relx = 0.61, rely = 0.00, relwidth = 0.28, relheight= 0.5)
		self.progressbar.start()

		self.inware_label = tk.Label(self.info_frame, text="NGINE v1.0 :: Python ver.", font=("Consolas", 14), bg=bgcolor, fg='white')

		self.CMONITOR1 = tk.Label(self.info_frame, text="Current Monitor 1", font=("Consolas", 14), bg=bgcolor, fg='white')

		self.CMONITOR2 = tk.Label(self.info_frame, text="Current Monitor 2", font=("Consolas", 14), bg=bgcolor, fg='white')

		stats_img = ImageTk.PhotoImage(Image.open("Assets/barcode_icon.png").resize((50,50), Image.Resampling.LANCZOS))
		self.BarcodeButton2 = customtkinter.CTkButton(self.info_frame, image = barcode_img, text = "", fg_color = bgcolor, corner_radius = 0, border_width = 0)
		self.BarcodeButton2.place(relx = 0.11, rely = 0.51, relwidth = 0.05, relheight= 0.49)
		#stats_img = ImageTk.PhotoImage(Image.open("Assets/stats.png").resize((50,50), Image.Resampling.LANCZOS))
		#self.StatsButton = customtkinter.CTkButton(self.info_frame, image = stats_img, text = "", fg_color = bgcolor, corner_radius = 0, border_width = 0)
		#self.StatsButton.place(relx = 0.11, rely = 0.51, relwidth = 0.05, relheight= 0.49)
		#self.progressbar1 = customtkinter.CTkProgressBar(self.info_frame, corner_radius = 0, fg_color = '#810D0D', progress_color = '#62D94E', mode = 'determinate', indeterminate_speed = 1)
		#self.progressbar1.place(relx = 0.16, rely = 0.51, relwidth = 0.3, relheight= 0.49)
		#self.progressbar1.set(0.5)

		sum_img = ImageTk.PhotoImage(Image.open("Assets/sum.png").resize((50,50), Image.Resampling.LANCZOS))
		self.StatsButton = customtkinter.CTkButton(self.info_frame, image = sum_img, text = "", fg_color = bgcolor, corner_radius = 0, border_width = 0)
		self.StatsButton.place(relx = 0.46, rely = 0.51, relwidth = 0.05, relheight= 0.49)
		self.sum_label = customtkinter.CTkLabel(self.info_frame, text="0", font=("Consolas", 20), text_color = 'white', bg_color='white', fg_color=bgcolor, corner_radius = 0)
		self.sum_label.place(relx=0.51, rely=0.51, relwidth=0.1,relheight=0.49)

		self.id_entry = customtkinter.CTkEntry(self.info_frame, font=("Consolas", 20), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.id_entry.place(relx=0.61, rely=0.51, relwidth=0.28,relheight=0.49)

		exit_img = ImageTk.PhotoImage(Image.open("Assets/exit_icon.png").resize((45,45), Image.Resampling.LANCZOS))
		self.exit_button = customtkinter.CTkButton(self.info_frame, image = exit_img, text = "", fg_color = "#810D0D", corner_radius = 4, border_width = 0, command = lambda: self.exit(controller))
		self.exit_button.place(relx = 0.95, rely = 0, relwidth = 0.05, relheight= 0.5)

		minimize_img = ImageTk.PhotoImage(Image.open("Assets/minimize_icon.png").resize((40,40), Image.Resampling.LANCZOS))
		self.minimize_button = customtkinter.CTkButton(self.info_frame, image = minimize_img, text = "", fg_color = "#E5AE59", corner_radius = 4, border_width = 0, command = lambda: self.minimize(controller))
		self.minimize_button.place(relx = 0.9, rely = 0, relwidth = 0.05, relheight= 0.5)

		self.F1_button = customtkinter.CTkButton(self.info_frame, text = "F1", fg_color = "#B4B4B4", corner_radius = 4, border_width = 0)
		self.F1_button.place(relx = 0.9, rely = 0.51, relwidth = 0.05, relheight= 0.49)

		self.F2_button = customtkinter.CTkButton(self.info_frame, text = "F2", fg_color = "#B4B4B4", corner_radius = 4, border_width = 0)
		self.F2_button.place(relx = 0.95, rely = 0.51, relwidth = 0.05, relheight= 0.49)

		grid_frame = customtkinter.CTkFrame(self, bg_color=bgcolor, fg_color=bgcolor, corner_radius = 4)
		grid_frame.place(relx=0.6525, rely=0.12, relwidth=0.682, relheight=0.867, anchor='n')

		self.Tree = ttk.Treeview(grid_frame)
		self.Tree.column("#0", width=0, minwidth=0, stretch=tk.NO)

		self.Tree2 = ttk.Treeview(grid_frame)
		self.Tree2.column("#0", width=0, minwidth=0, stretch=tk.NO)

		self.order = "idle"
		self.state = "idle"

		self.DGRID1_iid = 0
		self.DGRID2_iid = 0

	def setStop(self):
		self.PlayButton.configure(image = self.stop_img)

	def setRun(self):
		self.PlayButton.configure(image = self.run_img)

	def exit(self, controller):
		global loop_flag
		loop_flag = False
		global update_UI
		update_UI = False

	def minimize(self, controller):
		controller.wm_state('iconic')

	def goTable(self, controller):
		controller.show_frame(1)

	def StartStop(self, controller):
		if(self.state == "idle"):
			self.order = "run"
		elif(self.state == "running"):
			self.order = "stop"

	def getAllLbox(self):
		return self.lbox.get("0.0", tk.END)

	def addToLbox(self, message):
		if(TestData.log_flag == False):
			return
		self.lbox.insert(str(self.next_lbox_index)+'.0', str(message)+'\n')
		self.lbox.see(tk.END)
		self.next_lbox_index = self.next_lbox_index + 1

	def clearLbox(self):
		self.next_lbox_index = 1
		self.lbox.delete("0.0",tk.END)

	def setPBar(self, value):
		if(value == -1):
			self.progressbar.configure(mode = "indeterminate")
			self.progressbar.start()
		else:
			print("CHECK")
			self.progressbar.configure(mode = "determinate")
			self.progressbar.stop()
			self.progressbar.set(value)

#UI sub class, test table page
class TablePage(tk.Frame):

	def __init__(self, parent, controller):

		tk.Frame.__init__(self, parent)

		self.controller = controller

		bgcolor = "#181818"
		green = "#62D94E"

		self.canvas = tk.Canvas(self, height=1080, width=1920, bg='white')
		self.canvas.pack()

		menu_frame = tk.Frame(self, bg='white')
		menu_frame.place(relx=0.5, rely=0.01, relwidth=0.99, relheight=0.04, anchor='n')

		self.cbox = ttk.Combobox(menu_frame, values=[], font=("Consolas", 16))
		self.cbox.place(relx = 0.001, rely=0.001, relwidth = 0.15, relheight = 0.98)

		self.load_img = ImageTk.PhotoImage(Image.open("Assets/load_icon.png").resize((35,35), Image.Resampling.LANCZOS))
		self.loadButton = customtkinter.CTkButton(menu_frame, image = self.load_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.loadTable(controller))
		self.loadButton.place(relx = 0.155, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.entry = customtkinter.CTkEntry(menu_frame, font=("Consolas", 16), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.entry.place(relx = 0.209, rely=0.001, relwidth = 0.1, relheight = 0.98)

		self.save_img = ImageTk.PhotoImage(Image.open("Assets/save_icon.png").resize((35,35), Image.Resampling.LANCZOS))
		self.saveButton = customtkinter.CTkButton(menu_frame, image = self.save_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.saveTable(controller))
		self.saveButton.place(relx = 0.309, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.reload_img = ImageTk.PhotoImage(Image.open("Assets/reload_icon.png").resize((40,40), Image.Resampling.LANCZOS))
		self.reloadButton = customtkinter.CTkButton(menu_frame, image = self.reload_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.reload(controller))
		self.reloadButton.place(relx = 0.36, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.row_img = ImageTk.PhotoImage(Image.open("Assets/addrow_icon.png").resize((35,35), Image.Resampling.LANCZOS))
		self.addRowButton = customtkinter.CTkButton(menu_frame, image = self.row_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.addRow())
		self.addRowButton.place(relx = 0.42, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.rowentry = customtkinter.CTkEntry(menu_frame, font=("Consolas", 16), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.rowentry.place(relx = 0.47, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.drow_img = ImageTk.PhotoImage(Image.open("Assets/deleterow_icon.png").resize((35,35), Image.Resampling.LANCZOS))
		self.deleteRowButton = customtkinter.CTkButton(menu_frame, image = self.drow_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.deleteRow())
		self.deleteRowButton.place(relx = 0.53, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.drowentry = customtkinter.CTkEntry(menu_frame, font=("Consolas", 16), bg_color='white', fg_color=bgcolor, text_color = "white", corner_radius = 0, border_width = 0)
		self.drowentry.place(relx = 0.58, rely=0.001, relwidth = 0.05, relheight = 0.98)

		self.back_img = ImageTk.PhotoImage(Image.open("Assets/back_icon.png").resize((35,35), Image.Resampling.LANCZOS))
		self.backButton = customtkinter.CTkButton(menu_frame, image = self.back_img, bg_color = "#FFFFFF", fg_color = bgcolor, corner_radius = 0, text = "", command = lambda: self.back(controller))
		self.backButton.place(relx = 0.95, rely=0.001, relwidth = 0.05, relheight = 0.98)

		style = ttk.Style(self)
		style.theme_use("alt")

		#style.configure("Treeview", background="gray", foreground="white", fieldbackground="black", font=("Consolas", 16))

		style.configure("Treeview", font=("Consolas", 16), background = bgcolor, fieldbackground = bgcolor, foreground="white", rowheight = 24)
		style.configure('Treeview.Heading', background=bgcolor, foreground="#FFFFFF", font=("Consolas", 16), fieldbackground = "white")

		tree_frame = tk.Frame(self, bg='white', bd=2)
		tree_frame.place(relx=0.5, rely=0.06, relwidth=0.99, relheight=0.93, anchor='n')

		self.Tree = ttk.Treeview(tree_frame)
		self.Tree.place(relx = 0.00, rely=0.00, relwidth=1, relheight=1)
		self.Tree["columns"] = ("ID", "C0", "C1","C2","C3","C4","C5","C6","C7","C8","C9")
		self.Tree.column("#0", width=0, minwidth=0, stretch=tk.NO)
		self.Tree.column("ID", width=20, minwidth=0, stretch=tk.YES)
		self.Tree.column("C0", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C1", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C2", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C3", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C4", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C5", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C6", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C7", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C8", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.column("C9", width=100, minwidth=0, stretch=tk.YES)
		self.Tree.heading("ID", text="#", anchor=tk.W)
		self.Tree.heading("C0", text="C0", anchor=tk.W)
		self.Tree.heading("C1", text="C1", anchor=tk.W)
		self.Tree.heading("C2", text="C2", anchor=tk.W)
		self.Tree.heading("C3", text="C3", anchor=tk.W)
		self.Tree.heading("C4", text="C4", anchor=tk.W)
		self.Tree.heading("C5", text="C5", anchor=tk.W)
		self.Tree.heading("C6", text="C6", anchor=tk.W)
		self.Tree.heading("C7", text="C7", anchor=tk.W)
		self.Tree.heading("C8", text="C8", anchor=tk.W)
		self.Tree.heading("C9", text="C9", anchor=tk.W)
		self.Tree.tag_configure("yellow",background="#e6e600", foreground="black")

		self.Tree.tag_configure("none",background="#ffffff", foreground="#000000")
		self.Tree.tag_configure("blue",background="#66b3ff", foreground="black")
		self.Tree.tag_configure("green",background="#66ff66", foreground="black")
		self.Tree.tag_configure("orange",background="#ffb366", foreground="black")
		self.Tree.tag_configure("red",background="#FF3636", foreground="#ffffff")
		self.Tree.tag_configure("gray",background="#767676", foreground="#ffffff")
		self.Tree.tag_configure("black",background="#000000", foreground="#ffffff")
		self.Tree.bind('<3>', self.edit)
		self.Tree.bind('<1>', self.setLine)

		self.treeScroll = ttk.Scrollbar(tree_frame)
		self.treeScroll.configure(command=self.Tree.yview, orient="vertical")
		self.treeScroll.place(relx = 0.99, rely=0.03, relwidth=0.008, relheight=0.967)
		self.Tree.configure(yscrollcommand=self.treeScroll.set)

		self.xtreeScroll = ttk.Scrollbar(self)
		self.xtreeScroll.configure(command=self.Tree.xview, orient="horizontal")
		self.xtreeScroll.place(relx = 0.008, rely=0.972, relwidth=0.9765, relheight=0.015)
		self.Tree.configure(xscrollcommand=self.xtreeScroll.set)

		#self.Tree.insert(parent='',index='end',iid=0, text = "parent", values = ("0", "Word test", "Word test", "Word test", "Word test","Word test","Word test","Word test","Word test","Word test","Word test"), tag="black")

		self.updateCBox()
		self.TestTable = TestTable(self)

	def updateCBox(self):
		files = [f for f in listdir("TestTables") if isfile(join("TestTables", f))]
		self.cbox["values"] = files

	def loadTable(self, controller):
		TestData.pointer = None
		self.controller.clearLbox()
		#self.TestTable.loadTableInfo()
		self.TestTable.loadTableInfoOds()

	def saveTable(self, controller):
		self.TestTable.saveTableOds()
		self.updateCBox()

	def back(self, controller):
		controller.show_frame(0)

	def setLine(self, event):
		if self.Tree.identify_region(event.x, event.y) == 'cell':
			item = self.Tree.identify_row(event.y)
			self.rowentry.delete(0, tk.END)
			self.drowentry.delete(0, tk.END)
			self.rowentry.insert(0,item)
			self.drowentry.insert(0,item)

	def edit(self, event):

		print("Do nothing")
			
	def addRow(self):
		startindex = int(self.rowentry.get())
		number_rows = len(self.Tree.get_children())
		self.Tree.insert(parent='',index='end',iid=number_rows, text = "parent", values = ("-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"), tag="black")
		var = self.Tree.get_children()
		for k in range(number_rows - 1, startindex, -1):
			self.Tree.move(int(var[k]), self.Tree.parent(int(var[k])), self.Tree.index(int(var[k]))+1)

	def deleteRow(self):
		var = self.Tree.get_children()
		self.Tree.delete(var[int(self.drowentry.get())])

	def reload(self, controller):
		TestData.pointer = None
		self.controller.clearLbox()
		self.entry.delete(0, 100)
		self.entry.insert(0, self.cbox.get())
		self.saveTable(controller)
		self.loadTable(controller)

updatePeriod = 0.016
#UI update async call
async def updateUI(UI):
	global updatePeriod
	global update_UI
	update_UI = True
	while(update_UI == True):
		if(updatePeriod == -1):
			await asyncio.sleep(0.5)
		else:
			UI.update()
			await asyncio.sleep(updatePeriod)
	print("UI updater died.")
	
#MAIN
async def main():
	loop = asyncio.get_event_loop()
	NewUI = UI()
	TestLoop = Loop(NewUI)
	all_groups =  await asyncio.gather(updateUI(NewUI), TestLoop.flowManager())

	active = active_children()
	for child in active:
		child.terminate()
	for child in active():
		child.join()

if __name__ == "__main__": asyncio.run(main())