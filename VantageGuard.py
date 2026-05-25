import threading
import keyboard
import pystray
import subprocess
import winreg
import comtypes.client
import tkinter as tk
from tkinter import simpledialog, messagebox
from PIL import Image, ImageDraw
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

# --- Global States and Config ---
is_mic_muted = False
is_cam_muted = False
is_loc_muted = False

hotkeys = {
    'mic': 'f22',
    'cam': 'f23',
    'loc': 'f24'
}

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
    trigger_ui_update() # Update UI instantly for responsiveness
    
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
    """Safely updates both the system tray and the Tkinter GUI."""
    if tray_icon:
        tray_icon.icon = create_icon_image(is_mic_muted, is_cam_muted, is_loc_muted)
        tray_icon.title = f"Mic: {'MUTED' if is_mic_muted else 'LIVE'} | Cam: {'MUTED' if is_cam_muted else 'LIVE'} | Loc: {'MUTED' if is_loc_muted else 'LIVE'}"
    
    if app_ui:
        # Tkinter needs UI updates to happen on the main thread
        app_ui.root.after(0, app_ui.refresh_colors)


def create_icon_image(mic_muted, cam_muted, loc_muted):
    """Generates the 3-way split icon for the system tray."""
    image = Image.new('RGB', (64, 64))
    draw = ImageDraw.Draw(image)
    
    draw.rectangle([0, 0, 21, 64], fill=('red' if mic_muted else 'green'))
    draw.rectangle([21, 0, 42, 64], fill=('red' if cam_muted else 'green'))
    draw.rectangle([42, 0, 64, 64], fill=('red' if loc_muted else 'green'))
    
    draw.line([21, 0, 21, 64], fill='black', width=2)
    draw.line([42, 0, 42, 64], fill='black', width=2)
    return image

# --- Tkinter GUI Application ---

class VantageGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VantageGuard")
        self.root.geometry("350x220")
        self.root.resizable(False, False)
        
        # Override the close button (X) to hide instead of quit
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Create three frames (rows) for Mic, Cam, Loc
        self.mic_frame = tk.Frame(root, pady=10, padx=10)
        self.mic_frame.pack(fill='both', expand=True)
        
        self.cam_frame = tk.Frame(root, pady=10, padx=10)
        self.cam_frame.pack(fill='both', expand=True)

        self.loc_frame = tk.Frame(root, pady=10, padx=10)
        self.loc_frame.pack(fill='both', expand=True)

        # --- Mic Controls ---
        self.lbl_mic_hotkey = tk.Label(self.mic_frame, text=f"Hotkey: {hotkeys['mic'].upper()}", width=12, bg='white')
        self.lbl_mic_hotkey.pack(side='left', padx=5)
        tk.Button(self.mic_frame, text="Set Hotkey", command=lambda: self.set_hotkey('mic')).pack(side='left', padx=5)
        tk.Button(self.mic_frame, text="Toggle Mic", command=toggle_mic).pack(side='left', padx=5)

        # --- Cam Controls ---
        self.lbl_cam_hotkey = tk.Label(self.cam_frame, text=f"Hotkey: {hotkeys['cam'].upper()}", width=12, bg='white')
        self.lbl_cam_hotkey.pack(side='left', padx=5)
        tk.Button(self.cam_frame, text="Set Hotkey", command=lambda: self.set_hotkey('cam')).pack(side='left', padx=5)
        tk.Button(self.cam_frame, text="Toggle Cam", command=toggle_cam).pack(side='left', padx=5)

        # --- Loc Controls ---
        self.lbl_loc_hotkey = tk.Label(self.loc_frame, text=f"Hotkey: {hotkeys['loc'].upper()}", width=12, bg='white')
        self.lbl_loc_hotkey.pack(side='left', padx=5)
        tk.Button(self.loc_frame, text="Set Hotkey", command=lambda: self.set_hotkey('loc')).pack(side='left', padx=5)
        tk.Button(self.loc_frame, text="Toggle Loc", command=toggle_loc).pack(side='left', padx=5)

        self.refresh_colors()

    def refresh_colors(self):
        """Updates the background color of the frames based on current hardware states."""
        self.mic_frame.config(bg='red' if is_mic_muted else 'green')
        self.cam_frame.config(bg='red' if is_cam_muted else 'green')
        self.loc_frame.config(bg='red' if is_loc_muted else 'green')

    def hide_window(self):
        """Hides the GUI but keeps the app running in the system tray."""
        self.root.withdraw()

    def show_window(self):
        """Restores the GUI from the system tray."""
        self.root.deiconify()
        self.root.lift()

    def set_hotkey(self, target):
        """Prompts user for a new hotkey and re-binds it via the keyboard module."""
        current = hotkeys[target]
        new_key = simpledialog.askstring("Set Hotkey", f"Enter new hotkey for {target.upper()}\n(e.g., f24, ctrl+shift+m):", initialvalue=current)
        
        if new_key:
            new_key = new_key.lower().strip()
            try:
                # Test if the keyboard module accepts the string format
                keyboard.parse_hotkey(new_key) 
                
                # Unbind old, bind new
                keyboard.remove_hotkey(current)
                
                if target == 'mic':
                    keyboard.add_hotkey(new_key, toggle_mic)
                    self.lbl_mic_hotkey.config(text=f"Hotkey: {new_key.upper()}")
                elif target == 'cam':
                    keyboard.add_hotkey(new_key, toggle_cam)
                    self.lbl_cam_hotkey.config(text=f"Hotkey: {new_key.upper()}")
                elif target == 'loc':
                    keyboard.add_hotkey(new_key, toggle_loc)
                    self.lbl_loc_hotkey.config(text=f"Hotkey: {new_key.upper()}")
                
                hotkeys[target] = new_key
            except Exception as e:
                messagebox.showerror("Error", f"Invalid hotkey format.\n\nError: {e}")

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
    
    # 1. Fetch initial states
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    is_cam_muted = get_initial_cam_state()
    is_loc_muted = get_initial_loc_state()

    # 2. Bind initial default hotkeys
    keyboard.add_hotkey(hotkeys['mic'], toggle_mic)
    keyboard.add_hotkey(hotkeys['cam'], toggle_cam)
    keyboard.add_hotkey(hotkeys['loc'], toggle_loc)

    # 3. Start System Tray Icon in a Background Thread
    threading.Thread(target=run_tray, daemon=True).start()

    # 4. Start Tkinter Main Window on the Main Thread
    root = tk.Tk()
    app_ui = VantageGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()