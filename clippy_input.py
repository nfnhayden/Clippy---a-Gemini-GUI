import keyboard
import time
from PyQt6.QtCore import QThread, pyqtSignal

class GlobalKeyHook(QThread):
    activated = pyqtSignal()

    def __init__(self, hook_win_key=False):
        super().__init__()
        self.running = True
        self.hook_win_key = hook_win_key

    def run(self):
        # We want to hook the Windows key if requested.
        worked = False
        if self.hook_win_key:
            print("Attempting to hook 'windows' key...")
            try:
                # Check if we can suppress (requires sudo/admin)
                keyboard.on_press_key('windows', self.on_activated, suppress=True)
                print("Successfully hooked 'windows' key (Start Menu blocked).")
                worked = True
            except ImportError:
                 print("Could not suppress 'windows' key (requires Admin).")
            except Exception as e:
                 print(f"Failed to hook 'windows' key: {e}.")
        
        if not worked:
            print("Using fallback hotkey: 'win+shift+c'.")
            keyboard.add_hotkey('win+shift+c', self.on_activated)

        while self.running:
            time.sleep(0.1)

    def on_activated(self, event=None):
        self.activated.emit()

    def stop(self):
        self.running = False
        try:
            keyboard.unhook_all()
        except:
            pass
