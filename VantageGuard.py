import threading
import keyboard
import pystray
import subprocess
import winreg
import comtypes.client
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import configparser
import os
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

# --- Configuration & File Handling ---
CONFIG_DIR = os.path.join(os.getenv('APPDATA'), 'VantageGuard')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.ini')

hotkeys = {
    'mic': 'f22',
    'cam': 'f23',
    'loc': 'f24'
}

def load_config():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if 'Hotkeys' in config:
            hotkeys['mic'] = config['Hotkeys'].get('mic', hotkeys['mic'])
            hotkeys['cam'] = config['Hotkeys'].get('cam', hotkeys['cam'])
            hotkeys['loc'] = config['Hotkeys'].get('loc', hotkeys['loc'])
    else:
        save_config()

def save_config():
    config = configparser.ConfigParser()
    config['Hotkeys'] = hotkeys
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)

# --- Global States ---
is_mic_muted = False
is_cam_muted = False
is_loc_muted = False

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

def toggle_cam():
    global is_cam_muted
    is_cam_muted = not is_cam_muted
    trigger_ui_update() 
    
    try:
        if is_cam_muted:
            subprocess.run(["sc", "config", "FrameServer", "start=", "disabled"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            subprocess.run(["sc", "stop", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.run(["sc", "config", "FrameServer", "start=", "demand"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            subprocess.run(["sc", "start", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError:
        print("Failed to toggle camera service.")
        is_cam_muted = not is_cam_muted
        trigger_ui_update()

def toggle_loc():
    global is_loc_muted
    is_loc_muted = not is_loc_muted
    state_arg = "0" if is_loc_muted else "1"
    trigger_ui_update()
    
    try:
        subprocess.run(["SystemSettingsAdminFlows.exe", "SetCamSystemGlobal", "location", state_arg], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    except Exception:
        try:
            registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
            state_str = "Deny" if is_loc_muted else "Allow"
            winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, state_str)
            winreg.CloseKey(key)
        except Exception:
            is_loc_muted = not is_loc_muted
            trigger_ui_update()

# --- Initialization Checks ---

def get_initial_cam_state():
    try:
        result = subprocess.check_output(["sc", "qc", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW, text=True)
        return "DISABLED" in result.upper()
    except Exception:
        return False

def get_initial_loc_state():
    try:
        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "Value")
        winreg.CloseKey(key)
        return value == "Deny"
    except Exception:
        return False

# --- UI Sync Logic ---

def trigger_ui_update():
    if tray_icon:
        tray_icon.icon = create_icon_image(is_mic_muted, is_cam_muted, is_loc_muted)
        tray_icon.title = f"Mic: {'MUTED' if is_mic_muted else 'LIVE'} | Cam: {'MUTED' if is_cam_muted else 'LIVE'} | Loc: {'MUTED' if is_loc_muted else 'LIVE'}"
    
    if app_ui:
        app_ui.root.after(0, app_ui.refresh_colors)

def create_icon_image(mic_muted, cam_muted, loc_muted):
    image = Image.new('RGB', (64, 64))
    draw = ImageDraw.Draw(image)
    
    draw.rectangle([0, 0, 21, 64], fill=('red' if mic_muted else 'green'))
    draw.rectangle([21, 0, 42, 64], fill=('red' if cam_muted else 'green'))
    draw.rectangle([42, 0, 64, 64], fill=('red' if loc_muted else 'green'))
    
    draw.line([21, 0, 21, 64], fill='black', width=2)
    draw.line([42, 0, 42, 64], fill='black', width=2)
    return image

# --- CustomTkinter GUI Application ---

class HotkeyCatcher(ctk.CTkToplevel):
    def __init__(self, parent, target_name):
        super().__init__(parent)
        self.title("Listening...")
        self.geometry("380x160") # Widened the listening popup slightly
        self.resizable(False, False)
        
        self.transient(parent)
        self.grab_set()

        self.result = None
        self.is_active = True
        
        ctk.CTkLabel(self, text=f"Set Hotkey for {target_name.upper()}", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(25, 5))
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
        
        # Widen the default layout and set a minimum size
        self.root.geometry("540x320")
        self.root.minsize(450, 280)
        
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Make the main window grid stretchable
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        # Create three frames, telling them to stick to all edges (nsew)
        self.mic_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.mic_frame.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="nsew")
        
        self.cam_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.cam_frame.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")

        self.loc_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.loc_frame.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="nsew")

        self._build_row(self.mic_frame, 'mic', toggle_mic)
        self._build_row(self.cam_frame, 'cam', toggle_cam)
        self._build_row(self.loc_frame, 'loc', toggle_loc)

        self.refresh_colors()

    def _build_row(self, parent_frame, target, toggle_cmd):
        # Configure the inner frame's grid so column 0 (the label) eats all extra horizontal space
        parent_frame.grid_columnconfigure(0, weight=1)
        # Ensure the row stretches to center the elements vertically
        parent_frame.grid_rowconfigure(0, weight=1)
        
        # Label (Pushed to the left)
        lbl = ctk.CTkLabel(parent_frame, text=f"Hotkey: {hotkeys[target].upper()}", font=ctk.CTkFont(weight="bold", size=14), text_color="white")
        lbl.grid(row=0, column=0, padx=20, pady=15, sticky="w")
        
        if target == 'mic': self.lbl_mic_hotkey = lbl
        elif target == 'cam': self.lbl_cam_hotkey = lbl
        elif target == 'loc': self.lbl_loc_hotkey = lbl

        # Buttons (Pushed to the right)
        ctk.CTkButton(parent_frame, text="Set Hotkey", width=100, fg_color="#333333", hover_color="#444444", command=lambda: self.set_hotkey(target)).grid(row=0, column=1, padx=10, pady=15)
        ctk.CTkButton(parent_frame, text=f"Toggle {target.capitalize()}", width=100, fg_color="transparent", border_width=2, text_color="white", command=toggle_cmd).grid(row=0, column=2, padx=20, pady=15)

    def refresh_colors(self):
        self.mic_frame.configure(fg_color=COLOR_MUTED if is_mic_muted else COLOR_LIVE)
        self.cam_frame.configure(fg_color=COLOR_MUTED if is_cam_muted else COLOR_LIVE)
        self.loc_frame.configure(fg_color=COLOR_MUTED if is_loc_muted else COLOR_LIVE)

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def set_hotkey(self, target):
        current = hotkeys[target]
        
        listener = HotkeyCatcher(self.root, target)
        self.root.wait_window(listener)
        
        new_key = listener.result
        if new_key:
            try:
                try: keyboard.remove_hotkey(current)
                except ValueError: pass
                
                if target == 'mic':
                    keyboard.add_hotkey(new_key, toggle_mic)
                    self.lbl_mic_hotkey.configure(text=f"Hotkey: {new_key.upper()}")
                elif target == 'cam':
                    keyboard.add_hotkey(new_key, toggle_cam)
                    self.lbl_cam_hotkey.configure(text=f"Hotkey: {new_key.upper()}")
                elif target == 'loc':
                    keyboard.add_hotkey(new_key, toggle_loc)
                    self.lbl_loc_hotkey.configure(text=f"Hotkey: {new_key.upper()}")
                
                hotkeys[target] = new_key
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
    tray_icon = pystray.Icon("VantageGuard", create_icon_image(is_mic_muted, is_cam_muted, is_loc_muted), "VantageGuard", menu)
    tray_icon.run()

# --- Main Boot Sequence ---

def main():
    global is_mic_muted, is_cam_muted, is_loc_muted, app_ui
    
    load_config()
    
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    is_cam_muted = get_initial_cam_state()
    is_loc_muted = get_initial_loc_state()

    keyboard.add_hotkey(hotkeys['mic'], toggle_mic)
    keyboard.add_hotkey(hotkeys['cam'], toggle_cam)
    keyboard.add_hotkey(hotkeys['loc'], toggle_loc)

    threading.Thread(target=run_tray, daemon=True).start()

    root = ctk.CTk()
    app_ui = VantageGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()