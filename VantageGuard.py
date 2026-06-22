import threading
import keyboard
import pystray
import comtypes.client
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import configparser
import os
import pyaudio
import collections
from PIL import Image, ImageDraw
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

# --- Setup CustomTkinter Theme ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Modern Status Colors
COLOR_LIVE = "#2A8C55"  # Soft Green
COLOR_MUTED = "#C64747" # Soft Red
COLOR_NEUTRAL = "#2B2B2B"

# --- Configuration & File Handling ---
CONFIG_DIR = os.path.join(os.getenv('APPDATA'), 'VantageGuard')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.ini')

settings = {
    'mic_hotkey': 'f22',
    'delay_val': 'No Delay'
}

DELAY_MAP = {
    "No Delay": 0.0,
    "0.1 sec": 0.1,
    "0.25 sec": 0.25,
    "0.5 sec": 0.5,
    "1 sec": 1.0,
    "2 sec": 2.0,
    "3 sec": 3.0
}

def load_config():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if 'Settings' in config:
            settings['mic_hotkey'] = config['Settings'].get('mic_hotkey', settings['mic_hotkey'])
            settings['delay_val'] = config['Settings'].get('delay_val', settings['delay_val'])
    else:
        save_config()

def save_config():
    config = configparser.ConfigParser()
    config['Settings'] = settings
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)

# --- Global States ---
is_mic_muted = False
is_monitoring = False
monitor_thread = None

tray_icon = None
app_ui = None

# --- Hardware / OS Control Functions ---

def get_mic_endpoint():
    try:
        device_enumerator = comtypes.client.CreateObject("{BCDE0395-E52F-467C-8E3D-C4579291692E}", interface=IMMDeviceEnumerator)
        mic = device_enumerator.GetDefaultAudioEndpoint(1, 1)
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        print(f"Error accessing microphone: {e}")
        return None

def toggle_mic():
    global is_mic_muted
    CoInitialize() 
    mic_volume = get_mic_endpoint()
    if mic_volume:
        current_mute = mic_volume.GetMute()
        is_mic_muted = not current_mute
        mic_volume.SetMute(is_mic_muted, None)
    CoUninitialize()
    trigger_ui_update()

def get_mic_volume():
    CoInitialize()
    mic_volume = get_mic_endpoint()
    vol = 1.0
    if mic_volume:
        vol = mic_volume.GetMasterVolumeLevelScalar()
    CoUninitialize()
    return vol

def set_mic_volume(val):
    CoInitialize()
    mic_volume = get_mic_endpoint()
    if mic_volume:
        mic_volume.SetMasterVolumeLevelScalar(float(val), None)
    CoUninitialize()
    if app_ui:
        app_ui.lbl_vol_val.configure(text=f"{int(float(val)*100)}%")

# --- Audio Monitoring Thread ---

def audio_monitor_loop():
    CHUNK = 1024
    RATE = 44100
    p = pyaudio.PyAudio()
    
    try:
        stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
        stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, output=True, frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"Failed to open audio streams: {e}")
        p.terminate()
        return

    empty_chunk = b'\x00' * (CHUNK * 2) 
    buffer = collections.deque()
    
    current_delay_str = settings['delay_val']
    
    def get_target_chunks(delay_seconds):
        return int((delay_seconds * RATE) / CHUNK)

    target_chunks = get_target_chunks(DELAY_MAP.get(current_delay_str, 0.0))

    while is_monitoring:
        try:
            data = stream_in.read(CHUNK, exception_on_overflow=False)
            
            new_delay_str = settings['delay_val']
            if new_delay_str != current_delay_str:
                current_delay_str = new_delay_str
                target_chunks = get_target_chunks(DELAY_MAP.get(current_delay_str, 0.0))
            
            while len(buffer) < target_chunks:
                buffer.append(empty_chunk)
            while len(buffer) > target_chunks and len(buffer) > 0:
                buffer.popleft()

            if target_chunks > 0:
                buffer.append(data)
                out_data = buffer.popleft()
            else:
                out_data = data
                
            stream_out.write(out_data)
            
        except Exception as e:
            print(f"Audio stream error: {e}")
            break

    stream_in.stop_stream()
    stream_in.close()
    stream_out.stop_stream()
    stream_out.close()
    p.terminate()

def toggle_monitoring():
    global is_monitoring, monitor_thread
    
    if not is_monitoring:
        is_monitoring = True
        monitor_thread = threading.Thread(target=audio_monitor_loop, daemon=True)
        monitor_thread.start()
    else:
        is_monitoring = False

    if app_ui:
        app_ui.btn_monitor.configure(
            text="Stop Monitoring" if is_monitoring else "Start Monitoring",
            fg_color=COLOR_LIVE if is_monitoring else "transparent"
        )

def update_delay(choice):
    settings['delay_val'] = choice
    save_config()

# --- UI Sync Logic ---

def trigger_ui_update():
    if tray_icon:
        tray_icon.icon = create_icon_image(is_mic_muted)
        tray_icon.title = f"Mic: {'MUTED' if is_mic_muted else 'LIVE'}"
    
    if app_ui:
        app_ui.root.after(0, app_ui.refresh_colors)

def create_icon_image(mic_muted):
    image = Image.new('RGB', (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 64, 64], fill=('red' if mic_muted else 'green'))
    return image

# --- CustomTkinter GUI Application ---

class HotkeyCatcher(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Listening...")
        self.geometry("380x160")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None
        self.is_active = True
        
        ctk.CTkLabel(self, text="Set Hotkey for MIC", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(25, 5))
        ctk.CTkLabel(self, text="Press your new key combination now...\n(Press 'Esc' to cancel)", text_color="gray").pack()
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self.catch_keys, daemon=True).start()

    def catch_keys(self):
        hk = keyboard.read_hotkey(suppress=False)
        if self.is_active:
            self.after(0, self.finish, hk)

    def finish(self, hk):
        if hk != 'esc':
            self.result = hk
        self.on_close()

    def on_close(self):
        self.is_active = False
        self.destroy()

class VantageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VantageGuard")
        
        # Increased height for three distinct frames
        self.root.geometry("540x330")
        self.root.minsize(480, 330)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        # 1. Microphone Toggle Frame
        self.mic_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.mic_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="nsew")
        self.mic_frame.grid_columnconfigure(0, weight=1)
        self.mic_frame.grid_rowconfigure(0, weight=1)
        
        self.lbl_mic_hotkey = ctk.CTkLabel(self.mic_frame, text=f"Mic Hotkey: {settings['mic_hotkey'].upper()}", font=ctk.CTkFont(weight="bold", size=14), text_color="white")
        self.lbl_mic_hotkey.grid(row=0, column=0, padx=20, pady=15, sticky="w")
        
        ctk.CTkButton(self.mic_frame, text="Set Hotkey", width=100, fg_color="#333333", hover_color="#444444", command=self.set_hotkey).grid(row=0, column=1, padx=10, pady=15)
        ctk.CTkButton(self.mic_frame, text="Toggle Mic", width=100, fg_color="transparent", border_width=2, text_color="white", command=toggle_mic).grid(row=0, column=2, padx=20, pady=15)

        # 2. Microphone Volume Frame (Neutral Color)
        self.vol_frame = ctk.CTkFrame(self.root, corner_radius=10, fg_color=COLOR_NEUTRAL)
        self.vol_frame.grid(row=1, column=0, padx=20, pady=(10, 10), sticky="nsew")
        self.vol_frame.grid_columnconfigure(0, weight=1)
        self.vol_frame.grid_rowconfigure(0, weight=1)
        
        ctk.CTkLabel(self.vol_frame, text="Mic Volume:", font=ctk.CTkFont(weight="bold", size=14), text_color="white").grid(row=0, column=0, padx=20, pady=15, sticky="w")
        
        self.vol_slider = ctk.CTkSlider(self.vol_frame, from_=0.0, to=1.0, command=set_mic_volume)
        self.vol_slider.grid(row=0, column=1, padx=10, pady=15, sticky="ew")
        
        self.lbl_vol_val = ctk.CTkLabel(self.vol_frame, text="100%", width=40, font=ctk.CTkFont(weight="bold"))
        self.lbl_vol_val.grid(row=0, column=2, padx=20, pady=15, sticky="e")

        # 3. Live Audio Monitoring Frame
        self.mon_frame = ctk.CTkFrame(self.root, corner_radius=10, fg_color=COLOR_NEUTRAL)
        self.mon_frame.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="nsew")
        self.mon_frame.grid_columnconfigure(0, weight=1)
        self.mon_frame.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(self.mon_frame, text="Live Monitoring", font=ctk.CTkFont(weight="bold", size=14), text_color="white").grid(row=0, column=0, padx=20, pady=15, sticky="w")

        self.delay_dropdown = ctk.CTkOptionMenu(
            self.mon_frame, 
            values=list(DELAY_MAP.keys()),
            command=update_delay,
            width=120
        )
        self.delay_dropdown.set(settings['delay_val'])
        self.delay_dropdown.grid(row=0, column=1, padx=10, pady=15)

        self.btn_monitor = ctk.CTkButton(
            self.mon_frame, 
            text="Start Monitoring", 
            width=120, 
            fg_color="transparent", 
            border_width=2, 
            text_color="white", 
            command=toggle_monitoring
        )
        self.btn_monitor.grid(row=0, column=2, padx=20, pady=15)

        self.refresh_colors()

    def refresh_colors(self):
        # Only the main mic toggle frame flashes colors now
        self.mic_frame.configure(fg_color=COLOR_MUTED if is_mic_muted else COLOR_LIVE)

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def set_hotkey(self):
        current = settings['mic_hotkey']
        listener = HotkeyCatcher(self.root)
        self.root.wait_window(listener)
        
        new_key = listener.result
        if new_key:
            try:
                try: keyboard.remove_hotkey(current)
                except ValueError: pass
                
                keyboard.add_hotkey(new_key, toggle_mic)
                self.lbl_mic_hotkey.configure(text=f"Mic Hotkey: {new_key.upper()}")
                
                settings['mic_hotkey'] = new_key
                save_config()
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not bind hotkey.\n\nError: {e}")

# --- System Tray Setup ---

def on_quit(icon, item):
    global is_monitoring
    is_monitoring = False # Stop audio thread
    icon.stop()
    if app_ui:
        app_ui.root.quit()

def on_show(icon, item):
    if app_ui:
        app_ui.show_window()

def run_tray():
    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem('Show Window', on_show, default=True),
        pystray.MenuItem('Quit', on_quit)
    )
    tray_icon = pystray.Icon("VantageGuard", create_icon_image(is_mic_muted), "VantageGuard", menu)
    tray_icon.run()

# --- Main Boot Sequence ---

def main():
    global is_mic_muted, app_ui
    
    load_config()
    
    # Initialize Mic State
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    keyboard.add_hotkey(settings['mic_hotkey'], toggle_mic)

    threading.Thread(target=run_tray, daemon=True).start()

    # GUI Boot
    root = ctk.CTk()
    app_ui = VantageGUI(root)
    
    # Sync initial slider value
    initial_vol = get_mic_volume()
    app_ui.vol_slider.set(initial_vol)
    app_ui.lbl_vol_val.configure(text=f"{int(initial_vol*100)}%")
    
    root.mainloop()

if __name__ == '__main__':
    main()