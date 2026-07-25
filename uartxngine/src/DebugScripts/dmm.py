import pyvisa

def getResource(ID):
    global VISA_objs
    for i in range(len(VISA_objs)):
        if(VISA_objs[i] is None):
            continue

        if(ID in VISA_objs[i]["ID"]):
            return VISA_objs[i]["RESOURCE"]
    raise Exception("VISA object not found for ID: " + str(ID))

VISA_objs = [None]*20

rm = pyvisa.ResourceManager()
VISA_resources = rm.list_resources()

for i in range(len(VISA_resources)):

	if(len(VISA_resources[i]) < 40):
		continue

	VISA_objs[i] = {"ID": VISA_resources[i], "RESOURCE": rm.open_resource(VISA_resources[i])}
	VISA_objs[i]["RESOURCE"].timeout = 1000
	print(VISA_objs[i]["ID"] + " opened @ " + str(i) + " timeout: " + str(1000))
	print("Querying IDN..")
	print(VISA_objs[i]["RESOURCE"].query("*IDN?"))

print(getResource("DP2A243200206").write("INST:NSEL 1"))
print(getResource("DP2A243200206").write("VOLT 24V"))
print(getResource("DP2A243200206").write("CURR 1A"))
print(getResource("DP2A243200206").write("OUTP ON"))

print("--")

print(getResource("MM3A253500446").query("*IDN?"))

rcv = getResource("MM3A253500446").query("MEAS:VOLT:DC? AUTO,DEF,(@201)")
print(rcv)
values = rcv.split(',')
for value in values:
    print(str(i) + " : " + str(value))