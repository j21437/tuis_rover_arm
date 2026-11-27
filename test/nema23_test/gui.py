import tkinter as tk
from tkinter import ttk, messagebox
import time
import sys
if sys.platform == "win32":
    import ctypes
import serial
from serial.tools import list_ports

PPR = 80000

class App:
    def __init__(self, root):
        self.root = root
        root.title('TMC5160 RMT Motor Test | 25:1 | V3.1 CURRENT')
        root.geometry('720x880')
        self.s = None
        self.buf = bytearray()
        self.link = False
        self.state = 'NOT_READY'
        self.last_rx = 0
        self.next_ping = 0
        self.hello_at = 0
        self.waiting = False
        self.wait_until = 0
        self.jog_key = None
        self.jog_source = None
        self.mouse_button = None
        self.keys_down = set()
        self.release_jobs = {}
        self.next_jkeep = 0
        self.jog_mode = tk.BooleanVar(value=False)
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
        self.stop_btn=tk.Button(b,text='STOP / 励磁解除',bg='#a92323',fg='white',command=self.stop); self.stop_btn.pack(side='left',expand=True,fill='x',padx=(8,0))
        h=ttk.LabelFrame(f,text='負荷試験：位置保持',padding=8); h.pack(fill='x',pady=(8,0))
        self.current_choice=tk.StringVar(value='0.5')
        self.current_info=tk.StringVar(value='電流設定：未確認')
        cr=ttk.Frame(h); cr.pack(fill='x',pady=(0,4))
        ttk.Label(cr,text='回転・保持電流 (A RMS)').pack(side='left')
        self.current_combo=ttk.Combobox(cr,textvariable=self.current_choice,values=('0.5','1.0','1.5','2.0'),width=5,state='readonly')
        self.current_combo.pack(side='left',padx=5)
        self.current_btn=ttk.Button(cr,text='電流を適用',command=self.apply_current); self.current_btn.pack(side='left')
        ttk.Label(h,textvariable=self.current_info).pack(anchor='w')
        self.hold_btn=ttk.Button(h,text='位置保持 ON（設定電流）',command=self.enable_hold)
        self.hold_btn.pack(fill='x')
        self.hold_status=tk.StringVar(value='保持OFF')
        ttk.Label(h,textvariable=self.hold_status,font=('',11,'bold')).pack(anchor='w')
        ttk.Label(h,text='通常停止は保持継続。STOP・通信断・異常時は励磁解除。負荷を支持して試験。',wraplength=620).pack(anchor='w')
        j=ttk.LabelFrame(f,text='手動ジョグ操作（押している間だけ回転）',padding=8); j.pack(fill='x',pady=(10,0))
        jr=ttk.Frame(j); jr.pack(fill='x')
        ttk.Checkbutton(jr,text='キーボード操作を有効にする',variable=self.jog_mode,command=self.toggle_jog).pack(side='left')
        ttk.Button(jr,text='キー操作に戻る',command=self.arm_jog).pack(side='right')
        ttk.Label(j,text='A：逆転   /   D：正転   ｜   速度は上の設定を使用').pack(anchor='w')
        ttk.Label(j,text='キーを離す・両方押す・ウィンドウから離れると停止').pack(anchor='w')
        self.key_pad=ttk.Label(j,text='キー操作エリア（ここをクリックしてA / D）',takefocus=True,relief='groove',padding=5)
        self.key_pad.pack(fill='x',pady=(4,0))
        self.key_pad.bind('<Button-1>',lambda event:self.arm_jog())
        mouse_row=ttk.Frame(j); mouse_row.pack(fill='x',pady=(6,0))
        self.jog_buttons={}
        for k,label in (('a','← 逆転（長押し）'),('d','正転（長押し） →')):
            button=ttk.Button(mouse_row,text=label,takefocus=True)
            button.pack(side='left',expand=True,fill='x',padx=3,ipady=8)
            self.jog_buttons[k]=button
            button.bind('<ButtonPress-1>',lambda event,k=k:self.mouse_press(event,k))
            button.bind('<ButtonRelease-1>',self.mouse_release)
            button.bind('<Leave>',self.mouse_leave)
        ttk.Label(j,text='マウスはチェック不要。ボタンを離す / 枠外に出ると停止。').pack(anchor='w')
        self.bar=ttk.Progressbar(f,maximum=1); self.bar.pack(fill='x',pady=(12,2))
        self.count=tk.StringVar(value='0 / 0 pulses'); ttk.Label(f,textvariable=self.count).pack(anchor='w')
        self.log=tk.Text(f,height=10,wrap='word',font=('Consolas',10)); self.log.pack(fill='both',expand=True,pady=(8,0))
        root.bind('<KeyPress>',self.key_press,add='+')
        root.bind('<KeyRelease>',self.key_release,add='+')
        root.bind('<FocusOut>',self.focus_out,add='+')
        root.bind('<ButtonRelease-1>',self.mouse_release,add='+')
        root.bind('<Unmap>',self.window_unmap,add='+')
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
            (self.init_btn, self.link and self.state not in ('MOVING','HOLDING') and not self.waiting and not self.jog_key),
            (self.hold_btn, self.link and self.state == 'READY' and not self.waiting and not self.jog_key),
            (self.current_btn, self.link and self.state == 'READY' and not self.waiting and not self.jog_key),
            (self.current_combo, self.link and self.state == 'READY' and not self.waiting and not self.jog_key),
            (self.go, self.link and self.state in ('READY','HOLDING') and not self.waiting and not self.jog_key),
        ):
            if enabled and widget.instate(['disabled']):
                widget.state(['!disabled'])
            elif not enabled and widget.instate(['!disabled']):
                widget.state(['disabled'])
        self.hold_status.set('HOLDING / 位置保持中' if self.state=='HOLDING' else '回転中（保持状態は停止後に表示）' if self.state=='MOVING' else '保持OFF（通信状態を確認）' if self.s and self.state=='NOT_READY' else '保持OFF / 未確認' if not self.s else '保持OFF')
        ready = bool(self.s and self.link and self.state in ('READY','HOLDING') and not self.waiting and not self.jog_key)
        for k, button in self.jog_buttons.items():
            active = self.jog_source == 'mouse' and self.jog_key == k
            enabled = ready or active
            if enabled and button.instate(['disabled']): button.state(['!disabled'])
            elif not enabled and button.instate(['!disabled']): button.state(['disabled'])
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
            if cmd not in ('PING','JKEEP'): self.logline('> '+cmd)
            return True
        except (serial.SerialException,OSError) as e:
            self.logline('通信エラー: '+str(e)); self.disconnect(send_stop=False); return False
    def disconnect(self,send_stop=True):
        self.clear_jog(); self.jog_mode.set(False)
        s=self.s
        if s and send_stop:
            try: s.write(b'STOP\n')
            except (serial.SerialException,OSError): pass
        self.s=None
        if s:
            try: s.close()
            except OSError: pass
        self.current_info.set('電流設定：未確認')
        self.link=False; self.waiting=False; self.state='NOT_READY'; self.status.set('切断 / 動作中なら電源を確認'); self.controls()
    def initialize(self):
        if self.send('INIT'): self.waiting=True; self.wait_until=time.monotonic()+4; self.controls()
    def move(self):
        if not self.s or not self.link or self.state not in ('READY','HOLDING') or self.waiting or self.jog_key:
            return
        try: a,p,d=self.params()
        except (ValueError,OverflowError): messagebox.showerror('入力エラー','角度1～360°、速度0.25～5rpm'); return
        if self.send(f'MOVE {a} {p} {d}'):
            self.waiting=True; self.wait_until=time.monotonic()+3; self.status.set('回転指令送信済み / 応答待ち'); self.controls()
    def apply_current(self):
        if not self.s or not self.link or self.state!='READY' or self.waiting or self.jog_key:
            return
        ma={'0.5':500,'1.0':1000,'1.5':1500,'2.0':2000}.get(self.current_choice.get())
        if ma is None: return
        if self.send(f'CURRENT {ma}'):
            self.current_info.set('電流設定：応答待ち')
            self.waiting=True; self.wait_until=time.monotonic()+3; self.controls()

    def enable_hold(self):
        if not self.s or not self.link or self.state!='READY' or self.waiting or self.jog_key:
            return
        if self.send('HOLD'):
            self.waiting=True; self.wait_until=time.monotonic()+3; self.controls()

    def normal_jog_stop(self):
        if not self.jog_key: return
        self.clear_jog()
        if self.send('JSTOP'):
            self.waiting=True; self.wait_until=time.monotonic()+3; self.controls()

    def clear_jog(self):
        self.jog_key=None
        self.jog_source=None
        self.mouse_button=None

    def stop(self):
        self.clear_jog()
        if self.send('STOP'): self.waiting=True; self.wait_until=time.monotonic()+3; self.controls()
    def receive(self,msg):
        if msg!='PONG': self.logline(msg)
        if msg=='HELLO RMT_GUI_V3_1':
            self.link=True; self.last_rx=time.monotonic(); self.status.set('通信OK / 初期化してください'); self.send('STATUS')
        elif msg.startswith('HELLO '):
            self.logline('ファームウェアのバージョン不一致。V3.1を書き込んでください。'); self.disconnect()
        elif msg.startswith('CURRENT '):
            ma=msg.split()[1:]
            if ma in (['500'],['1000'],['1500'],['2000']):
                amps=f'{int(ma[0])/1000:.1f}'
                self.current_choice.set(amps)
                self.current_info.set(f'適用済み：設定 {amps} A RMS（回転・保持共通、概算）')
        elif msg=='PONG':
            self.last_rx=time.monotonic()
            return
        elif msg.startswith('STATE '):
            parts=msg.split()
            if len(parts)==4 and parts[1] in ('READY','HOLDING','MOVING','NOT_READY'):
                try:
                    n,total=map(int,parts[2:])
                    self.bar['maximum']=max(1,total); self.bar['value']=n if total else 0
                    self.count.set(f'{n:,} / {total:,} pulses' if total else f'{n:,} pulses（ジョグ）' if n or parts[1]=='MOVING' else '0 pulses')
                except ValueError: return
                previous=self.state
                self.state=parts[1]; self.waiting=False
                if self.state=='NOT_READY' or (previous=='MOVING' and self.state=='READY'):
                    self.clear_jog()
                self.status.set({'READY':'READY / 回転可能','HOLDING':'HOLDING / 位置保持中','MOVING':'回転中','NOT_READY':'初期化が必要'}[self.state])
        elif msg.startswith('START '): self.state='MOVING'; self.waiting=False; self.status.set('回転中')
        elif msg.startswith('ERR '):
            if self.jog_key or self.state in ('HOLDING','MOVING'): self.stop()
            self.waiting=False; self.status.set(msg)
            if self.state!='MOVING': self.state='NOT_READY'
        elif msg.startswith('END '): self.clear_jog(); self.waiting=False; self.status.set(msg); self.state='NOT_READY'
        self.controls()
    def arm_jog(self):
        self.jog_mode.set(True); self.toggle_jog()

    def toggle_jog(self):
        if not self.jog_mode.get():
            if self.jog_source == 'keyboard': self.stop()
        else:
            if sys.platform=='win32':
                # Keys already held when arming must be released before use.
                self.keys_down = {k for k in ('a','d') if self.physical_down(k)}
            self.key_pad.focus_set()
            self.logline('ジョグ有効：A / D を押している間だけ回転')

    @staticmethod
    def physical_down(k):
        return bool(ctypes.windll.user32.GetAsyncKeyState(ord(k.upper())) & 0x8000)

    @staticmethod
    def blocked_modifiers(event=None):
        if sys.platform == 'win32':
            # Do not interpret Tk's platform-dependent modifier mask as Alt.
            # High bit = key currently down; ignore toggle/lock bits.
            user32 = ctypes.windll.user32
            keys = ((0x11, 'Ctrl'), (0x12, 'Alt'),
                    (0x5B, 'Left Win'), (0x5C, 'Right Win'))
            return [name for vk, name in keys
                    if (user32.GetAsyncKeyState(vk) | user32.GetKeyState(vk)) & 0x8000]
        return ['Ctrl/Alt'] if event is not None and event.state & 0x000C else []

    @staticmethod
    def mouse_down():
        # Windows GetAsyncKeyState uses physical mouse button codes.
        user32=ctypes.windll.user32
        vk=0x02 if user32.GetSystemMetrics(23) else 0x01
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def focus_widget(self):
        try: return self.root.focus_get()
        except (KeyError,tk.TclError): return None

    def focus_safe(self):
        w=self.focus_widget()
        return (w is not None and w.winfo_toplevel()==self.root
                and w.winfo_class() not in ('Entry','TEntry','TCombobox','Text','Spinbox','TSpinbox'))

    def focus_out(self,event):
        self.root.after_idle(self.check_focus)

    def check_focus(self):
        if self.jog_key and not self.focus_safe(): self.stop()
        if self.focus_widget() is None:
            self.jog_mode.set(False)

    def window_unmap(self,event):
        if event.widget is self.root:
            if self.jog_key: self.stop()
            self.jog_mode.set(False)

    def start_jog(self,k,source,button=None):
        if self.jog_key:
            self.stop()
            return False
        if not self.focus_safe():
            self.logline('ジョグ拒否：入力欄またはウィンドウのフォーカスを確認')
            return False
        if not self.s or not self.link or self.state not in ('READY','HOLDING') or self.waiting:
            self.logline(f'ジョグ拒否：READY待ち (state={self.state}, waiting={self.waiting})')
            return False
        try:
            r=float(self.rpm.get())
            if not 0.25<=r<=5: raise ValueError()
            p=round(750/r)
        except (ValueError,OverflowError):
            self.status.set('速度0.25～5rpmを指定してください')
            self.logline('ジョグ拒否：速度設定が範囲外')
            return False
        if not self.send(f'JOG {p} {0 if k=="d" else 1}'): return False
        self.jog_key=k; self.jog_source=source; self.mouse_button=button
        self.next_jkeep=time.monotonic()+.12
        self.waiting=True; self.wait_until=time.monotonic()+3
        self.status.set('ジョグ指令送信済み / 応答待ち'); self.controls()
        return True

    @staticmethod
    def event_key(event):
        k=event.keysym.lower()
        if k in ('a','d'): return k
        if sys.platform=='win32': return {65:'a',68:'d'}.get(event.keycode)
        return None

    def key_press(self,event):
        k=self.event_key(event)
        if k is None: return
        if k in self.release_jobs:
            self.root.after_cancel(self.release_jobs.pop(k))
        if k in self.keys_down:
            return 'break' if self.jog_mode.get() and self.focus_safe() else None
        self.keys_down.add(k)
        # Any new A/D press during mouse jog stops it, never reverses it.
        if self.jog_source=='mouse':
            self.stop(); return 'break'
        if not self.jog_mode.get():
            self.logline(f'キー {k.upper()}：キーボード操作が無効')
            return
        if not self.focus_safe():
            self.logline(f'キー {k.upper()}：入力欄のフォーカスでジョグ禁止')
            return
        modifiers=self.blocked_modifiers(event)
        if modifiers:
            self.logline(f'ジョグ拒否：{", ".join(modifiers)} (state=0x{event.state:04X})')
            return
        self.logline(f'キー状態: 0x{event.state:04X} / 修飾キーなし')
        self.logline(f'KEY {k.upper()} (code={event.keycode})')
        opposite='a' if k=='d' else 'd'
        if self.jog_key or len(self.keys_down)>1 or (sys.platform=='win32' and self.physical_down(opposite)):
            if self.jog_key: self.stop()
            self.logline('ジョグ拒否：両方のキーを離してから操作')
            return 'break'
        self.start_jog(k,'keyboard')
        return 'break'

    def key_release(self,event):
        k=self.event_key(event)
        if k is None: return
        if sys.platform=='win32': self.finish_release(k)
        else:
            # X11 auto-repeat may emit synthetic release/press pairs.
            if k in self.release_jobs: self.root.after_cancel(self.release_jobs[k])
            self.release_jobs[k]=self.root.after(35,lambda: self.finish_release(k))
        if self.jog_mode.get() and self.focus_safe(): return 'break'

    def finish_release(self,k):
        self.release_jobs.pop(k,None); self.keys_down.discard(k)
        if self.jog_source=='keyboard' and self.jog_key==k:
            if not self.jog_mode.get() or not self.focus_safe() or (sys.platform=='win32' and self.blocked_modifiers()): self.stop()
            else: self.normal_jog_stop()

    def mouse_press(self,event,k):
        button=event.widget
        if self.jog_key:
            self.stop(); return 'break'
        if button.instate(['disabled']): return 'break'
        if self.keys_down or (sys.platform=='win32' and any(self.physical_down(x) for x in ('a','d'))):
            self.logline('ジョグ拒否：A/Dキーを離してください'); return 'break'
        button.focus_set()
        self.logline(f'MOUSE {k.upper()}')
        self.start_jog(k,'mouse',button)
        return 'break'

    def mouse_release(self,event):
        if self.jog_source=='mouse':
            # Release on the active button is normal; elsewhere is safety stop.
            if self.focus_safe() and self.mouse_inside(): self.normal_jog_stop()
            else: self.stop()
            return 'break'
        if event.widget in self.jog_buttons.values(): return 'break'

    def mouse_leave(self,event):
        if self.jog_source=='mouse' and event.widget is self.mouse_button:
            self.stop()

    def mouse_inside(self):
        b=self.mouse_button
        if b is None or not self.focus_safe() or not b.winfo_viewable(): return False
        x,y=b.winfo_pointerxy()
        return (b.winfo_rootx() <= x < b.winfo_rootx()+b.winfo_width()
                and b.winfo_rooty() <= y < b.winfo_rooty()+b.winfo_height())

    def tick(self):
        if sys.platform=='win32':
            if self.jog_source=='keyboard' and (not self.jog_mode.get() or not self.focus_safe()): self.stop()
            if self.jog_source=='keyboard' and self.blocked_modifiers():
                self.logline('ジョグ停止：修飾キーが押されました')
                self.stop()
            if self.jog_key and self.physical_down('a') and self.physical_down('d'): self.stop()
            if self.jog_source=='mouse' and any(self.physical_down(k) for k in ('a','d')): self.stop()
            for k in tuple(self.keys_down):
                if not self.physical_down(k): self.finish_release(k)
            if self.jog_source=='keyboard' and not self.physical_down(self.jog_key): self.normal_jog_stop()
        if self.jog_source=='keyboard' and (not self.jog_mode.get() or not self.focus_safe()): self.stop()
        if self.jog_source=='mouse':
            if not self.mouse_inside(): self.stop()
            elif sys.platform=='win32' and not self.mouse_down(): self.normal_jog_stop()
        if self.s:
            try:
                now=time.monotonic()
                if self.hello_at and now>=self.hello_at:
                    self.hello_at=0; self.send('HELLO')
                if self.s and self.jog_key and now>=self.next_jkeep:
                    self.next_jkeep=now+.12; self.send('JKEEP')
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
