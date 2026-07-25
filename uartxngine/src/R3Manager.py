import TestData
import UIManager
import keyboard
import tkinter as tk
import asyncio


async def READBCODE(line, UI):

    #0      1           2      3              7
	#R3     READBCODE   l,c,p  BOM_EXPECTED   exception_label

    UI.frames[0].barcode_entry.delete(0,tk.END)
    initial = UI.frames[0].barcode_entry.get()
    UI.frames[0].barcode_entry.focus()
    tries = 0
	
    try:
        while(True):        
            if(UI.frames[0].barcode_entry.get() != initial):
                await asyncio.sleep(1)
                bcode = str(UI.frames[0].barcode_entry.get())
                print("Barcode was read: " + str(bcode))
                TestData.setContent(line[2], bcode)
                break
            await asyncio.sleep(1)

    except Exception as e:
         raise Exception(line[7] + "::" + str(e))
