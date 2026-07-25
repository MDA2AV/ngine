from PIL import Image, ImageWin, ImageDraw, ImageFont
import TestData
import win32print
import win32ui
import sys

async def PRINT(line, UI):

    #0       1     2
    #Printer PRINT barcode

    barcode = TestData.getContent(line[2])
    #barcode_size = len(barcode)
    #n_zeros = 7 - barcode_size

    #for i in range(n_zeros):

        #barcode = '0' + barcode

    try:

        import qrcode
        from datetime import datetime

        #SN = "MC60_" + barcode + "_" + TestData.getContent("*2,0,23") + "_" + TestData.getContent("*3,0,23")
        #SN = "MC60_" + barcode + "_" + TestData.getContent("*39,1,24")
        SN = TestData.getContent("*35,1,24")
        serial = SN.split('-')[1]

        # Generating the QR code
        QRimage = qrcode.make(SN)

        # Saving image into a file
        QRimage.save(TestData.getContent(line[3]))

        UI.addToLbox("Printing label: " + SN)

        img = Image.open(TestData.getContent(line[3]))
        img = img.resize((200,200))

        background= Image.new('RGB', (220, 220), color = 'white')
        background.paste(img, (18,0))

        d1 = ImageDraw.Draw(background)
        myFont = ImageFont.truetype('arial.ttf', 28)
        d1.text((30, 195), serial, font=myFont, fill=0)
        background.save(TestData.getContent(line[3]))

        PHYSICALWIDTH = 10
        PHYSICALHEIGHT = 10

        printer_name = win32print.GetDefaultPrinter ()
        file_name = TestData.getContent(line[3])

        hDC = win32ui.CreateDC ()
        hDC.CreatePrinterDC (printer_name)
        printer_size = hDC.GetDeviceCaps (PHYSICALWIDTH), hDC.GetDeviceCaps (PHYSICALHEIGHT)

        bmp = Image.open (file_name)
        if bmp.size[0] < bmp.size[1]:
          bmp = bmp.rotate (90)

        hDC.StartDoc (file_name)
        hDC.StartPage ()

        dib = ImageWin.Dib (bmp)
        dib.draw (hDC.GetHandleOutput (), (0,0,printer_size[0],printer_size[1]), (0,0,200,200))

        hDC.EndPage ()
        hDC.EndDoc ()
        hDC.DeleteDC ()

    except Exception as e:

        raise Exception(line[7] + "::" + str(e))
