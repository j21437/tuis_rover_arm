import sys,time,serial
port=sys.argv[1] if len(sys.argv)>1 else 'COM17'
s=serial.Serial(port=None,baudrate=115200,timeout=.2,write_timeout=1)
s.port=port;s.dtr=False;s.rts=False
try:
    s.open();time.sleep(.6)
    print('Opened',port)
    s.write(b'HELLO\nPING\n');end=time.monotonic()+4;ok=set()
    while time.monotonic()<end:
        line=s.readline().decode('utf-8','replace').strip()
        if line: print(line);ok.add(line)
        if {'HELLO RMT_GUI_V1','PONG'}<=ok: break
    print('USB OK' if {'HELLO RMT_GUI_V1','PONG'}<=ok else 'USB FAILED: expected HELLO and PONG')
except (serial.SerialException,OSError) as e:
    print('USB FAILED:',e)
finally:
    s.close()
