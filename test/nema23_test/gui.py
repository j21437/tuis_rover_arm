import tkinter as tk
from tkinter import ttk, messagebox
import time
import serial
from serial.tools import list_ports

PPR = 80000

class App:
    def __init__(self, root):
        self.root = root
        root.title('TMC5160 RMT Motor Test | 25:1')
        root.geometry('640x650')
        self.s = None
        self.buf = bytearray()
        self.link = False
        self.state = 'NOT_READY'
        self.last_rx = 0
        self.next_ping = 0
        self.hello_at = 0
        self.waiting = False
        self.wait_until = 0
        f = ttk.Frame(root, padding=16); f.pack(fill='both', expand=True)
        ttk.Label(f, text='ステッピングモータ テスト', font=('',18,'bold')).pack(anchor='w')
        ttk.Label(f, text='25:1 / 16 microsteps / 80,000 pulses per output revolution').pack(anchor='w',pady=(0,12))
        c=ttk.Frame(f); c.pack(fill='x')
        self.port=tk.StringVar(value='COM17')
        self.combo=ttk.Combobox(c,textvariable=self.port,width=14); self.combo.pack(side='left')
        ttk.Button(c,text='更新',command=self.refresh).pack(side='left',padx=4)
        self.connect_btn=ttk.Button(c,text='接続',command=self.connect); self.connect_btn.pack(side='left',padx=4)
        ttk.Button(c,text='切断',command=self.disconnect).pack(side='left')
        self.init_btn=ttk.Button(f,text='TMC初期化（24V ON後）',command=self.initialize); self.init_btn.pack(fill='x',pady=10)
        self.status=tk.StringVar(value='未接続'); ttk.Label(f,textvariable=self.status,font=('',12,'bold')).pack(anchor='w')
        g=ttk.LabelFrame(f,text='移動指令（出力軸基準）',padding=10); g.pack(fill='x',pady=10)
        self.angle=tk.StringVar(value='90'); self.rpm=tk.StringVar(value='0.5'); self.direction=tk.IntVar(value=0)
        ttk.Label(g,text='相対角度 (°)').grid(row=0,column=0,sticky='w'); ttk.Entry(g,textvariable=self.angle,width=10).grid(row=0,column=1,sticky='w')
        presets=ttk.Frame(g); presets.grid(row=0,column=2,sticky='w')
        for a in (10,90,180,360): ttk.Button(presets,text=str(a),width=4,command=lambda a=a:self.angle.set(str(a))).pack(side='left')
        ttk.Label(g,text='速度 (rpm)').grid(row=1,column=0,sticky='w',pady=6); ttk.Combobox(g,textvariable=self.rpm,values=('0.25','0.5','1','2','3','4','5'),width=10).grid(row=1,column=1,sticky='w')
        ttk.Radiobutton(g,text='正方向',variable=self.direction,value=0).grid(row=2,column=0,sticky='w'); ttk.Radiobutton(g,text='逆方向',variable=self.direction,value=1).grid(row=2,column=1,sticky='w')
        self.preview=tk.StringVar(); ttk.Label(g,textvariable=self.preview).grid(row=3,column=0,columnspan=3,sticky='w',pady=(8,0))
        self.angle.trace_add('write',self.calc); self.rpm.trace_add('write',self.calc); self.calc()
        b=ttk.Frame(f); b.pack(fill='x')
        self.go=ttk.Button(b,text='回転開始',command=self.move); self.go.pack(side='left',expand=True,fill='x')
        self.stop_btn=tk.Button(b,text='stop/停止',bg='#a92323',fg='white',command=self.stop); self.stop_btn.pack(side='left',expand=True,fill='x',padx=(8,0))
        self.bar=ttk.Progressbar(f,maximum=1); self.bar.pack(fill='x',pady=(12,2))
        self.count=tk.StringVar(value='0 / 0 pulses'); ttk.Label(f,textvariable=self.count).pack(anchor='w')
        self.log=tk.Text(f,height=10,wrap='word',font=('Consolas',10)); self.log.pack(fill='both',expand=True,pady=(8,0))
        self.refresh(); self.controls(); root.protocol('WM_DELETE_WINDOW',self.close); root.after(40,self.tick)

    def refresh(self):
        self.combo['values']=[p.device for p in list_ports.comports()]
    def logline(self, msg):
        self.log.insert('end',msg+'\n'); self.log.see('end')
        if int(self.log.index('end-1c').split('.')[0])>400: self.log.delete('1.0','50.0')
    def params(self):
        a=int(self.angle.get()); r=float(self.rpm.get())
        if not 1<=a<=360 or not 0.25<=r<=5: raise ValueError('角度1～360°、速度0.25～5rpm')
        return a,round(750/r),self.direction.get()
    def calc(self,*_):
        try:
            a,p,d=self.params(); n=(PPR*a+180)//360
            self.preview.set(f'{n:,} pulses / 定速換算 {n*p/1e6:.1f} 秒')
        except (ValueError,OverflowError): self.preview.set('入力範囲を確認してください')
    def controls(self):
        # Only change the disabled bit when the enabled state changes.
        # Leave Tk's mouse hover and pressed states alone.
        for widget, enabled in (
            (self.connect_btn, self.s is None),
            (self.init_btn, self.link and self.state != 'MOVING' and not self.waiting),
            (self.go, self.link and self.state == 'READY' and not self.waiting),
        ):
            if enabled and widget.instate(['disabled']):
                widget.state(['!disabled'])
            elif not enabled and widget.instate(['!disabled']):
                widget.state(['disabled'])
        desired = 'normal' if self.s else 'disabled'
        if str(self.stop_btn.cget('state')) == 'disabled' and desired == 'normal':
            self.stop_btn.configure(state=desired)
        elif str(self.stop_btn.cget('state')) != 'disabled' and desired == 'disabled':
            self.stop_btn.configure(state=desired)
    def connect(self):
        if self.s: return
        s=None
        try:
            s=serial.Serial(port=None,baudrate=115200,timeout=0,write_timeout=0.3)
            s.port=self.port.get(); s.dtr=False; s.rts=False; s.open()
            self.s=s; self.buf.clear(); self.link=False; self.waiting=False; self.state='NOT_READY'
            now=time.monotonic(); self.hello_at=now+.6; self.last_rx=now; self.next_ping=now+.6
            self.status.set('接続中：HELLO応答待ち'); self.logline('Opened '+s.port)
        except Exception as e:
            if s: s.close()
            self.logline(str(e)); self.status.set('接続失敗')
        self.controls()
    def send(self,cmd):
        if not self.s: return False
        try:
            data=(cmd+'\n').encode('ascii')
            if self.s.write(data)!=len(data): raise serial.SerialTimeoutException('partial write')
            if cmd!='PING': self.logline('> '+cmd)
            return True
        except (serial.SerialException,OSError) as e:
            self.logline('通信エラー: '+str(e)); self.disconnect(send_stop=False); return False
    def disconnect(self,send_stop=True):
        s=self.s
        if s and send_stop:
            try: s.write(b'STOP\n')
            except (serial.SerialException,OSError): pass
        self.s=None
        if s:
            try: s.close()
            except OSError: pass
        self.link=False; self.waiting=False; self.state='NOT_READY'; self.status.set('切断 / 動作中なら電源を確認'); self.controls()
    def initialize(self):
        if self.send('INIT'): self.waiting=True; self.wait_until=time.monotonic()+4; self.controls()
    def move(self):
        if not self.s or not self.link or self.state != 'READY' or self.waiting:
            return
        try: a,p,d=self.params()
        except (ValueError,OverflowError): messagebox.showerror('入力エラー','角度1～360°、速度0.25～5rpm'); return
        if self.send(f'MOVE {a} {p} {d}'):
            self.waiting=True; self.wait_until=time.monotonic()+3; self.status.set('回転指令送信済み / 応答待ち'); self.controls()
    def stop(self):
        if self.send('STOP'): self.waiting=True; self.wait_until=time.monotonic()+3; self.controls()
    def receive(self,msg):
        if msg!='PONG': self.logline(msg)
        if msg=='HELLO RMT_GUI_V1':
            self.link=True; self.last_rx=time.monotonic(); self.status.set('通信OK / 初期化してください'); self.send('STATUS')
        elif msg=='PONG':
            self.last_rx=time.monotonic()
            return
        elif msg.startswith('STATE '):
            parts=msg.split()
            if len(parts)==4 and parts[1] in ('READY','MOVING','NOT_READY'):
                try: n,total=map(int,parts[2:]); self.bar['maximum']=max(1,total); self.bar['value']=n; self.count.set(f'{n:,} / {total:,} pulses')
                except ValueError: return
                self.state=parts[1]; self.waiting=False
                self.status.set({'READY':'READY / 回転可能','MOVING':'回転中','NOT_READY':'初期化が必要'}[self.state])
        elif msg.startswith('START '): self.state='MOVING'; self.waiting=False; self.status.set('回転中')
        elif msg.startswith('ERR '):
            self.waiting=False; self.status.set(msg)
            if self.state!='MOVING': self.state='NOT_READY'
        elif msg.startswith('END '): self.waiting=False; self.status.set(msg); self.state='NOT_READY'
        self.controls()
    def tick(self):
        if self.s:
            try:
                now=time.monotonic()
                if self.hello_at and now>=self.hello_at:
                    self.hello_at=0; self.send('HELLO')
                if self.s and now>=self.next_ping and not self.hello_at:
                    self.next_ping=now+.5; self.send('PING')
                if self.s:
                    self.buf.extend(self.s.read(min(self.s.in_waiting,4096)))
                    while b'\n' in self.buf:
                        raw,_,tail=self.buf.partition(b'\n'); self.buf=bytearray(tail)
                        self.receive(raw.decode('utf-8','replace').strip())
                    if len(self.buf)>8192: self.buf.clear()
                if self.s and now-self.last_rx>5:
                    self.logline('HELLO/PONG応答なし。COM番号・ファームウェア・USB接続を確認してください。'); self.disconnect()
                if self.s and self.waiting and now>self.wait_until:
                    self.logline('応答待ちタイムアウト。再送せず停止します。'); self.disconnect()
            except (serial.SerialException,OSError) as e:
                self.logline('通信エラー: '+str(e)); self.disconnect(send_stop=False)
        self.root.after(40,self.tick)
    def close(self):
        self.disconnect(); self.root.destroy()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
