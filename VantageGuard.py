import threading
import keyboard
import pystray
import subprocess
import winreg
import comtypes.client
from PIL import Image, ImageDraw
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

# Global state trackers
is_mic_muted = False
is_cam_muted = False
is_loc_muted = False

def get_mic_endpoint():
    """Locates the default microphone via Windows Core Audio API."""
    try:
        device_enumerator = comtypes.client.CreateObject(
            "{BCDE0395-E52F-467C-8E3D-C4579291692E}",
            interface=IMMDeviceEnumerator
        )
        mic = device_enumerator.GetDefaultAudioEndpoint(1, 1)
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        print(f"Error accessing microphone: {e}")
        return None

def toggle_mic(icon):
    """Toggles the system microphone mute state."""
    global is_mic_muted
    CoInitialize() 
    mic_volume = get_mic_endpoint()
    if mic_volume:
        current_mute = mic_volume.GetMute()
        is_mic_muted = not current_mute
        mic_volume.SetMute(is_mic_muted, None)
        update_tray_ui(icon)
    CoUninitialize()

def toggle_cam(icon):
    """Toggles the camera system-wide by disabling the FrameServer service."""
    global is_cam_muted
    is_cam_muted = not is_cam_muted
    update_tray_ui(icon)
    
    try:
        if is_cam_muted:
            subprocess.run(["sc", "config", "FrameServer", "start=", "disabled"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            subprocess.run(["sc", "stop", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.run(["sc", "config", "FrameServer", "start=", "demand"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            subprocess.run(["sc", "start", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError:
        print("Failed to toggle camera service. Ensure you are running as Administrator.")
        is_cam_muted = not is_cam_muted
        update_tray_ui(icon)

def toggle_loc(icon):
    """Toggles system-wide Location Services using Windows native Admin Flows."""
    global is_loc_muted
    is_loc_muted = not is_loc_muted
    
    # 0 = Disabled, 1 = Enabled
    state_arg = "0" if is_loc_muted else "1"
    update_tray_ui(icon)
    
    try:
        # This calls the exact same background executable that the Windows Settings UI uses
        subprocess.run(
            ["SystemSettingsAdminFlows.exe", "SetCamSystemGlobal", "location", state_arg], 
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True
        )
    except Exception as e:
        print("Failed to toggle location via AdminFlows, trying Registry fallback...")
        # Fallback to direct registry edit if the executable is blocked
        try:
            registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
            state_str = "Deny" if is_loc_muted else "Allow"
            winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, state_str)
            winreg.CloseKey(key)
        except Exception as e2:
            print("Failed to toggle location registry:", e2)
            is_loc_muted = not is_loc_muted
            update_tray_ui(icon)

def update_tray_ui(icon):
    """Updates the tray icon colors and hover text."""
    icon.icon = create_icon_image(is_mic_muted, is_cam_muted, is_loc_muted)
    
    mic_text = "MUTED" if is_mic_muted else "LIVE"
    cam_text = "MUTED" if is_cam_muted else "LIVE"
    loc_text = "MUTED" if is_loc_muted else "LIVE"
    icon.title = f"Mic: {mic_text} | Cam: {cam_text} | Loc: {loc_text}"

def create_icon_image(mic_muted, cam_muted, loc_muted):
    """Generates a 3-way split 64x64 icon: Left=Mic, Mid=Cam, Right=Loc."""
    image = Image.new('RGB', (64, 64))
    draw = ImageDraw.Draw(image)
    
    # Left Third (Microphone)
    draw.rectangle([0, 0, 21, 64], fill=('red' if mic_muted else 'green'))
    
    # Middle Third (Webcam)
    draw.rectangle([21, 0, 42, 64], fill=('red' if cam_muted else 'green'))
    
    # Right Third (Location)
    draw.rectangle([42, 0, 64, 64], fill=('red' if loc_muted else 'green'))
    
    # Add dividing lines
    draw.line([21, 0, 21, 64], fill='black', width=2)
    draw.line([42, 0, 42, 64], fill='black', width=2)
    
    return image

def on_quit(icon, item):
    icon.stop()

def get_initial_cam_state():
    try:
        result = subprocess.check_output(["sc", "qc", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW, text=True)
        return "DISABLED" in result.upper()
    except Exception:
        return False

def get_initial_loc_state():
    """Reads the Local Machine registry to find if location is system-wide disabled."""
    try:
        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "Value")
        winreg.CloseKey(key)
        return value == "Deny"
    except Exception:
        return False

def main():
    global is_mic_muted, is_cam_muted, is_loc_muted
    
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    is_cam_muted = get_initial_cam_state()
    is_loc_muted = get_initial_loc_state()

    menu = pystray.Menu(pystray.MenuItem('Quit', on_quit))
    tray_icon = pystray.Icon("VantageGuard", create_icon_image(is_mic_muted, is_cam_muted, is_loc_muted), "Initializing...", menu)
    update_tray_ui(tray_icon)

    keyboard.add_hotkey('ctrl+shift+m', lambda: toggle_mic(tray_icon))
    keyboard.add_hotkey('ctrl+shift+c', lambda: toggle_cam(tray_icon))
    keyboard.add_hotkey('ctrl+shift+l', lambda: toggle_loc(tray_icon))
    
    print("VantageGuard is running.")
    print("CRITICAL: You must run this script as an Administrator.")
    print("Press Ctrl+Shift+M for Microphone.")
    print("Press Ctrl+Shift+C for Webcam.")
    print("Press Ctrl+Shift+L for Location.")

    tray_icon.run()

if __name__ == '__main__':
    main()