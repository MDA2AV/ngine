import subprocess
from pathlib import Path
import asyncio

#subprocess.Popen(['cmd.exe', '/c', 'start', 'C:/Users/Admin.ONTPC12/Desktop/NGINERepo/uartxngine/src/flash/PK5.bat'], shell=True)

#cmd = "C:/Users/Admin.ONTPC12/Desktop/NGINERepo/uartxngine/src/flash/PK5.bat".split(',')
#ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
#out,err = ret.communicate()

async def func():
    cmd = "C:\\Users\\Admin.ONTPC12\\Desktop\\NGINERepo\\uartxngine\\src\\flash\\pk6.bat"
    ret = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    out,err = ret.communicate()

    print(out)
    print(err)

asyncio.run(func())