import threading
import keyboard
import pystray
import subprocess
import comtypes.client
from PIL import Image, ImageDraw
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

# Global state trackers
is_mic_muted = False
is_cam_muted = False

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
    """Toggles the camera system-wide by disabling and stopping the FrameServer service."""
    global is_cam_muted
    is_cam_muted = not is_cam_muted
    
    # Update UI immediately so it feels responsive
    update_tray_ui(icon)
    
    try:
        if is_cam_muted:
            # 1. Change startup type to 'disabled' so Windows CANNOT auto-restart it
            subprocess.run(["sc", "config", "FrameServer", "start=", "disabled"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            # 2. Stop the service (we don't use check=True here in case it's already stopped)
            subprocess.run(["sc", "stop", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # 1. Change startup type back to 'demand' (Windows Default: Manual)
            subprocess.run(["sc", "config", "FrameServer", "start=", "demand"], creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            # 2. Start the service again
            subprocess.run(["sc", "start", "FrameServer"], creationflags=subprocess.CREATE_NO_WINDOW)
            
    except subprocess.CalledProcessError:
        print("Failed to toggle camera service configuration. Ensure you are running as Administrator.")
        # Revert state on failure
        is_cam_muted = not is_cam_muted
        update_tray_ui(icon)

def update_tray_ui(icon):
    """Updates the tray icon colors and hover text."""
    icon.icon = create_icon_image(is_mic_muted, is_cam_muted)
    
    mic_text = "MUTED" if is_mic_muted else "LIVE"
    cam_text = "MUTED" if is_cam_muted else "LIVE"
    icon.title = f"Mic: {mic_text} | Cam: {cam_text}"

def create_icon_image(mic_muted, cam_muted):
    """Generates a split 64x64 icon: Left=Mic, Right=Cam."""
    image = Image.new('RGB', (64, 64))
    draw = ImageDraw.Draw(image)
    
    mic_color = 'red' if mic_muted else 'green'
    draw.rectangle([0, 0, 32, 64], fill=mic_color)
    
    cam_color = 'red' if cam_muted else 'green'
    draw.rectangle([32, 0, 64, 64], fill=cam_color)
    
    draw.line([32, 0, 32, 64], fill='black', width=2)
    
    return image

def on_quit(icon, item):
    icon.stop()

def get_initial_cam_state():
    """Checks if the Windows Camera Frame Server startup type is disabled."""
    try:
        # sc qc queries the configuration (startup type) instead of the current running status
        result = subprocess.check_output(
            ["sc", "qc", "FrameServer"], 
            creationflags=subprocess.CREATE_NO_WINDOW, 
            text=True
        )
        # If the start type is DISABLED, our lock is currently active
        return "DISABLED" in result.upper()
    except Exception:
        return False

def main():
    global is_mic_muted, is_cam_muted
    
    CoInitialize()
    mic = get_mic_endpoint()
    if mic:
        is_mic_muted = mic.GetMute()
    CoUninitialize()
    
    is_cam_muted = get_initial_cam_state()

    menu = pystray.Menu(pystray.MenuItem('Quit', on_quit))
    tray_icon = pystray.Icon("VantageGuard", create_icon_image(is_mic_muted, is_cam_muted), "Initializing...", menu)
    update_tray_ui(tray_icon)

    keyboard.add_hotkey('ctrl+shift+m', lambda: toggle_mic(tray_icon))
    keyboard.add_hotkey('ctrl+shift+c', lambda: toggle_cam(tray_icon))
    
    print("VantageGuard is running.")
    print("CRITICAL: You must run this script as an Administrator for the camera toggle to work.")
    print("Press Ctrl+Shift+M to toggle Microphone.")
    print("Press Ctrl+Shift+C to toggle Webcam.")

    tray_icon.run()

if __name__ == '__main__':
    main()