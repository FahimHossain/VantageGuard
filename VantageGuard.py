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
import struct
import time
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
COLOR_CANVAS = "#1E1E1E"

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
current_test_device_idx = None
input_devices_map = {}

current_waveform = [] # Holds the data for the visualizer

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

def get_input_devices():
    p = pyaudio.PyAudio()
    devices = {"System Default": None}
    try:
        default_api_info = p.get_default_host_api_info()
        default_api_index = default_api_info['index']
        
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0 and info['hostApi'] == default_api_index:
                devices[info['name']] = i
    except Exception as e:
        print(f"Error enumerating devices: {e}")
    finally:
        p.terminate()
    return devices

# --- Continuous Audio Engine ---

def audio_engine_loop():
    """Constantly runs to power the visualizer, selectively routes audio for monitoring."""
    global current_waveform
    CHUNK = 1024
    RATE = 44100
    p = pyaudio.PyAudio()
    
    while True: # Outer loop allows us to cleanly restart if the user changes the input device
        active_device = current_test_device_idx
        
        try:
            stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, 
                               input_device_index=active_device, frames_per_buffer=CHUNK)
            stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, output=True, 
                                frames_per_buffer=CHUNK)
        except Exception:
            time.sleep(1)
            continue

        empty_chunk = b'\x00' * (CHUNK * 2)
        buffer = collections.deque()
        current_delay_str = settings['delay_val']
        
        def get_target_chunks(delay_seconds):
            return int((delay_seconds * RATE) / CHUNK)

        target_chunks = get_target_chunks(DELAY_MAP.get(current_delay_str, 0.0))

        # Inner loop reads data as long as the device hasn't been changed
        while active_device == current_test_device_idx:
            try:
                data = stream_in.read(CHUNK, exception_on_overflow=False)
                
                # --- Visualizer Data Processing ---
                if len(data) == CHUNK * 2:
                    samples = struct.unpack(f"{CHUNK}h", data)
                    # Downsample 1024 points to ~64 points so Tkinter can draw it fast
                    step = CHUNK // 64
                    current_waveform = [samples[i] for i in range(0, CHUNK, step)]

                # --- Live Monitoring Routing ---
                if is_monitoring:
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
                else:
                    buffer.clear() # Keep buffer empty when not monitoring
                    
            except Exception:
                break # Stream crash, break to outer loop to reboot the streams

        stream_in.stop_stream()
        stream_in.close()
        stream_out.stop_stream()
        stream_out.close()

def toggle_monitoring():
    global is_monitoring
    is_monitoring = not is_monitoring

    if app_ui:
        app_ui.btn_monitor.configure(
            text="Stop Monitoring" if is_monitoring else "Start Monitoring",
            fg_color=COLOR_LIVE if is_monitoring else "transparent"
        )

def update_delay(choice):
    settings['delay_val'] = choice
    save_config()

def update_test_device(choice):
    global current_test_device_idx
    # This change breaks the while loop in the audio thread, forcing it to cleanly restart with the new device
    current_test_device_idx = input_devices_map.get(choice)

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
        
        # Taller window to fit the visualizer frame
        self.root.geometry("600x700")
        self.root.minsize(480, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=1)
        self.root.grid_rowconfigure(3, weight=1)

        # 1. Microphone Toggle Frame
        self.mic_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.mic_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="nsew")
        self.mic_frame.grid_columnconfigure(0, weight=1)
        self.mic_frame.grid_rowconfigure(0, weight=1)
        
        self.lbl_mic_hotkey = ctk.CTkLabel(self.mic_frame, text=f"Mic Hotkey: {settings['mic_hotkey'].upper()}", font=ctk.CTkFont(weight="bold", size=14), text_color="white")
        self.lbl_mic_hotkey.grid(row=0, column=0, padx=20, pady=15, sticky="w")
        
        ctk.CTkButton(self.mic_frame, text="Set Hotkey", width=100, fg_color="#333333", hover_color="#444444", command=self.set_hotkey).grid(row=0, column=1, padx=10, pady=15)
        ctk.CTkButton(self.mic_frame, text="Toggle Mic", width=100, fg_color="transparent", border_width=2, text_color="white", command=toggle_mic).grid(row=0, column=2, padx=20, pady=15)

        # 2. Microphone Volume Frame
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
        self.mon_frame.grid(row=2, column=0, padx=20, pady=(10, 10), sticky="nsew")
        self.mon_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(self.mon_frame, text="Live Monitoring", font=ctk.CTkFont(weight="bold", size=14), text_color="white").grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")

        self.delay_dropdown = ctk.CTkOptionMenu(self.mon_frame, values=list(DELAY_MAP.keys()), command=update_delay, width=120)
        self.delay_dropdown.set(settings['delay_val'])
        self.delay_dropdown.grid(row=0, column=1, padx=10, pady=(15, 5))

        self.btn_monitor = ctk.CTkButton(self.mon_frame, text="Start Monitoring", width=120, fg_color="transparent", border_width=2, text_color="white", command=toggle_monitoring)
        self.btn_monitor.grid(row=0, column=2, padx=20, pady=(15, 5))

        ctk.CTkLabel(self.mon_frame, text="Test Device:", font=ctk.CTkFont(weight="bold", size=14), text_color="white").grid(row=1, column=0, padx=20, pady=(5, 15), sticky="w")
        self.device_dropdown = ctk.CTkOptionMenu(self.mon_frame, values=list(input_devices_map.keys()), command=update_test_device)
        self.device_dropdown.set("System Default")
        self.device_dropdown.grid(row=1, column=1, columnspan=2, padx=10, pady=(5, 15), sticky="ew")

        # 4. Waveform Visualizer Frame
        self.vis_frame = ctk.CTkFrame(self.root, corner_radius=10, fg_color=COLOR_CANVAS)
        self.vis_frame.grid(row=3, column=0, padx=20, pady=(10, 20), sticky="nsew")
        
        # We pack the canvas inside its dedicated frame
        self.canvas = tk.Canvas(self.vis_frame, bg=COLOR_CANVAS, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_colors()
        self.draw_waveform() # Kick off the rendering loop

    def refresh_colors(self):
        self.mic_frame.configure(fg_color=COLOR_MUTED if is_mic_muted else COLOR_LIVE)

    def draw_waveform(self):
        # Only spend CPU drawing if the window is actually visible
        if self.root.winfo_exists() and self.root.state() == "normal":
            self.canvas.delete("wave")
            
            width = int(self.canvas.winfo_width())
            height = int(self.canvas.winfo_height())
            
            if width > 10 and height > 10: # Ensure canvas is rendered
                mid_y = height / 2
                data = current_waveform 
                
                if data and len(data) > 1:
                    points = []
                    x_step = width / (len(data) - 1)
                    
                    for i, val in enumerate(data):
                        x = i * x_step
                        # Convert 16-bit PCM integer (-32768 to 32767) to canvas Y coordinate
                        y = mid_y - (val / 32768.0) * mid_y
                        y = max(0, min(height, y)) # Clamp to boundaries
                        points.extend([x, y])
                    
                    # Waveform matches system status (Red if muted, Green if live)
                    line_color = COLOR_MUTED if is_mic_muted else COLOR_LIVE
                    self.canvas.create_line(*points, fill=line_color, width=2, tags="wave", smooth=True)
                else:
                    # Draw flatline if no data
                    line_color = COLOR_MUTED if is_mic_muted else COLOR_LIVE
                    self.canvas.create_line(0, mid_y, width, mid_y, fill=line_color, width=2, tags="wave")
                    
        # Request next frame (~25 fps)
        self.root.after(40, self.draw_waveform)

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
    global is_mic_muted, app_ui, input_devices_map
    
    load_config()
    
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    input_devices_map = get_input_devices()
    
    keyboard.add_hotkey(settings['mic_hotkey'], toggle_mic)

    # Boot background services
    threading.Thread(target=audio_engine_loop, daemon=True).start()
    threading.Thread(target=run_tray, daemon=True).start()

    # Boot GUI
    root = ctk.CTk()
    app_ui = VantageGUI(root)
    
    initial_vol = get_mic_volume()
    app_ui.vol_slider.set(initial_vol)
    app_ui.lbl_vol_val.configure(text=f"{int(initial_vol*100)}%")
    
    root.mainloop()

if __name__ == '__main__':
    main()