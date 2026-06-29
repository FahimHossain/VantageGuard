# VantageGuard

VantageGuard is a modern, feature-rich desktop application for Windows that provides comprehensive control over your microphone. Built with Python and CustomTkinter, it features global hotkey muting, live audio monitoring with customizable delays, an integrated WAV recorder, and a real-time responsive audio visualizer. 

##  Key Features

* **Global Hotkey Mic Mute:** Quickly mute/unmute your microphone from anywhere in the OS using customizable key bindings.
* **Push-To-Talk Mode:** Temporarily unmute your microphone using a hotkey.
* **Live Audio Monitoring:** Route your microphone input to your output device with adjustable delays to test how you sound.
* **Built-in Audio Recorder:** Record your microphone directly to `.wav` files with pause, resume, and stop functionality.
* **Real-Time Visualizer:** A smooth, live waveform display coupled with a dynamic peak decibel (dB) meter that features clipping detection (Green/Yellow/Red).
* **System Tray Integration:** Runs quietly in the background and minimizes to the Windows system tray while indicating mic status.
* **Hardware Sync:** Changes made in the app sync directly with the Windows Core Audio API, and vice-versa.

---

## Function Analysis & Architecture

The application is structured into several distinct modules handling OS interfacing, audio streaming, UI, and background states. 

### 1. Configuration & State Management
Manages persistent settings stored in the user's `APPDATA` directory.
* **`load_config()`**: Checks for the existence of `config.ini`. If found, it loads the saved hotkey and delay preferences into memory. If not, it triggers a save to create default settings.
* **`save_config()`**: Writes the current `settings` dictionary (containing the mic hotkey and delay values) to the configuration file.

### 2. Hardware / OS Control (PyCaw)
Interfaces directly with the Windows Core Audio API to manipulate system-level sound settings.
* **`get_mic_endpoint()`**: Initializes a COM object to locate and return the default system microphone endpoint.
* **`toggle_mic()`**: Reads the current mute state of the microphone endpoint, flips it, and applies the new state system-wide. Triggers a UI update to reflect the change.
* **`get_mic_volume()`**: Fetches the current master volume level (scalar value from 0.0 to 1.0) of the default microphone.
* **`set_mic_volume(val)`**: Adjusts the system microphone volume based on the UI slider input.
* **`get_input_devices()`**: Uses PyAudio to enumerate all available audio input devices on the host API, returning a mapped dictionary for the UI dropdown.

### 3. Continuous Audio Engine (PyAudio)
The backbone of the application, running on a dedicated daemon thread to process audio chunks without freezing the UI.
* **`audio_engine_loop()`**: The infinite loop that opens PyAudio input and output streams. 
  * **Visualizer Feed:** Extracts integer arrays from raw bytes to feed the `current_waveform` list.
  * **Recorder Feed:** Appends raw audio bytes to `recorded_frames` if the recording state is active.
  * **Live Monitor Feed:** Uses a `collections.deque` buffer to hold audio chunks based on the user's selected delay target, flushing them to the output stream.
* **`toggle_monitoring()`**: Flips the global boolean for live feedback and updates the UI button colors accordingly.
* **`update_delay(choice)`**: Updates the global settings dictionary with the new delay choice and saves it to the config.
* **`update_test_device(choice)`**: Updates the active input device index so the audio engine can reboot the stream with the correct hardware.

### 4. CustomTkinter User Interface
The front-end class `VantageGUI` handles all user interactions and canvas drawing.
* **`draw_waveform()`**: A recursive UI loop running every 40ms. It calculates the max amplitude (peak) to drive the vertical dB meter (applying a smooth visual decay) and dynamically maps the `current_waveform` data to an `x/y` plane to draw a smooth line on the Tkinter Canvas.
* **Recorder Logic (`action_record`, `action_pause`, `action_stop`, `save_recording`)**: Manages the state machine for the recorder. When stopped, `save_recording` writes the accumulated `recorded_frames` bytes into a properly formatted `.wav` file in the user's Documents folder.
* **Hotkey Management (`edit_hotkey`, `save_typed_hotkey`, `set_hotkey_popup`)**: Allows the user to manually type a hotkey string or use the `HotkeyCatcher` `CTkToplevel` window to physically record a keypress via the `keyboard` module.
* **`refresh_colors()`**: Updates the main microphone frame color (Soft Green for Live, Soft Red for Muted) to provide instant visual feedback on the mic's status.

### 5. System Tray & Boot Sequence
* **`run_tray()` / `create_icon_image()`**: Utilizes `pystray` to generate a dynamic system tray icon (green or red based on mute state) and handles minimizing/restoring the application.
* **`main()`**: The bootloader. It initializes the config file, fetches initial hardware states (volume and mute status), hooks the global keyboard listener, spawns the audio/tray background threads, and starts the CustomTkinter `mainloop`.

---

## 🚀 Installation & Requirements

### Simple Installation
Directly run the standalone VantageGuard.exe file


### Run using the python file
Ensure you have Python 3.8+ installed. You will need the following packages:
```bash
pip install customtkinter pystray comtypes pycaw pyaudio keyboard pillow
```


Running the App
Execute the python script directly:

```
python vantageguard.py
```