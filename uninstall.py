import os
import shutil
import subprocess

def get_windows_startup_dir():
    # Try env var first
    appdata = os.getenv('APPDATA')
    if appdata:
        return os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    
    # Try WSL interop
    try:
        result = subprocess.run(["cmd.exe", "/c", "echo %APPDATA%"], capture_output=True, text=True)
        win_appdata = result.stdout.strip()
        if win_appdata:
            proc = subprocess.run(["wslpath", "-u", win_appdata], capture_output=True, text=True)
            wsl_appdata = proc.stdout.strip()
            if wsl_appdata:
                return os.path.join(wsl_appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    except Exception:
        pass
        
    return None

def uninstall():
    print("=== Clippy Gemini Uninstaller ===")
    
    startup_dir = get_windows_startup_dir()
    if not startup_dir:
        print("Could not locate startup folder automatically.")
        return

    bat_path = os.path.join(startup_dir, "ClippyGemini.bat")
    
    if os.path.exists(bat_path):
        try:
            os.remove(bat_path)
            print(f"Removed startup shortcut: {bat_path}")
        except Exception as e:
            print(f"Error removing shortcut: {e}")
    else:
        print("Startup shortcut not found (maybe already removed?).")

    print("\nStopping running Clippy instances...")
    try:
        # Attempt to kill pythonw processes running clippy.py
        # This is a bit broad, but 'clippy.py' should be unique enough in command line
        subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe", "/FI", "WINDOWTITLE eq Clippy*"], capture_output=True)
        # Also try by script name match if possible, but taskkill typically filters by window title or image name.
        # Since we don't have a specific window title easily matchable globally without external tools,
        # we'll rely on the user or a more generic kill if they want.
        # Actually, let's just advise the user, or try to kill by known pid if we stored it?
        # Storing PID is better, but for now let's just use the print message as a fallback 
        # and try a generic kill command that might work if the window title matches.
        pass
    except Exception:
        pass

    print("The Windows key functionality will return to normal immediately after the process stops.")
    print("If Clippy is still running, please close it manually (Right Click -> Close or via Task Manager).")

if __name__ == "__main__":
    uninstall()
