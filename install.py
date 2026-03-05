import os
import sys
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
        # Convert Windows path to WSL path if needed
        if win_appdata:
            # Simple heuristic for WSL: C:\Users... -> /mnt/c/Users...
            # But 'wslpath' tool is better
            proc = subprocess.run(["wslpath", "-u", win_appdata], capture_output=True, text=True)
            wsl_appdata = proc.stdout.strip()
            if wsl_appdata:
                return os.path.join(wsl_appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    except Exception:
        pass
        
    return None

def create_startup_shortcut(target_script, python_exe, override_win_key=False):
    startup_dir = get_windows_startup_dir()
    if not startup_dir or not os.path.exists(startup_dir):
        print(f"Startup directory not found. Manual installation required.")
        return

    bat_path = os.path.join(startup_dir, "ClippyGemini.bat")
    
    # Create a bat file to launch python script
    # We use pythonw.exe if available to hide console, but here we use the python_exe provided
    
    # Check if we are in WSL but writing a Windows Batch file.
    # The Batch file will run on Windows, so it needs Windows paths for python and script.
    
    # Convert paths to Windows format if we are in WSL
    target_script_win = target_script
    python_exe_win = python_exe
    
    if os.path.exists("/usr/bin/wslpath"):
        try:
            target_script_win = subprocess.check_output(["wslpath", "-w", target_script], text=True).strip()
            # If python is linux python, this won't work on Windows directly unless via 'wsl python ...'
            # But the user likely wants to run this NATIVE on Windows if they are installing to Windows Startup.
            # If we are in WSL, we can't easily make a Windows native startup unless we use the Windows python.
            # Assuming the user runs this install script from the environment they intend to run Clippy in.
            
            # If running in WSL, the batch file should probably invoke `wsl.exe python3 ...`
            python_exe_win = "wsl.exe"
            # And we need the linux path for the argument
            target_script_win = target_script 
            
            # Re-construct command for WSL launch
            # wsl.exe python3 /mnt/c/.../clippy.py
            cmd = f'wsl.exe python3 "{target_script}"'
            
        except:
            pass
    else:
        # Native Windows Python
        # Force pythonw.exe to hide console
        pythonw = python_exe.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            print("Warning: pythonw.exe not found, falling back to python.exe (console will be visible)")
            pythonw = python_exe
        
        # Quote paths to handle spaces
        cmd = f'"{pythonw}" "{target_script}"'

    if override_win_key:
        cmd += " --override-win-key"
        
    with open(bat_path, "w") as f:
        f.write(f'@echo off\n')
        f.write(f'start "" {cmd}\n')
        
    print(f"Created startup shortcut at: {bat_path}")


def main():
    print("=== Clippy Gemini Installer ===")
    
    # 1. Check Python
    python_exe = sys.executable
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "clippy.py"))
    
    if not os.path.exists(script_path):
        print("Error: clippy.py not found.")
        return

    # 1.5 Check for 'gemini' command
    print("Checking for 'gemini' command...")
    gemini_path = shutil.which("gemini")
    
    # Also check via powershell/cmd just in case which() misses a ps1/cmd alias
    if not gemini_path:
        try:
            # Try powershell check
            subprocess.run(["powershell", "-Command", "Get-Command gemini"], capture_output=True, check=True)
            print("Found 'gemini' via PowerShell.")
        except subprocess.CalledProcessError:
            print("Warning: 'gemini' command not found in PATH.")
            print("This application requires the 'gemini' CLI tool to function.")
            print("Please ensure it is installed (e.g. 'npm install -g gemini-chat-cli' or similar).")
            choice = input("Continue installation anyway? (y/N): ").strip().lower()
            if choice != 'y':
                print("Installation aborted.")
                return
    else:
        print(f"Found 'gemini' at: {gemini_path}")
        # Check if gemini is logged in/interactive
        print("Checking gemini authentication...")
        
        # Method 1: Check for credential file (non-blocking)
        # Based on gemini-chat-cli source, creds are in ~/.gemini/oauth_creds.json
        home_dir = os.path.expanduser("~")
        creds_path = os.path.join(home_dir, ".gemini", "oauth_creds.json")
        
        has_creds = os.path.exists(creds_path)
        
        if has_creds:
            print(f"Found cached credentials at: {creds_path}")
            print("Gemini check passed.")
        else:
            print("Warning: encoded credential file not found.")
            # Fallback: check responsiveness with version command (fast, non-blocking)
            try:
                subprocess.run(["gemini", "--version"], capture_output=True, timeout=5)
                print("Gemini command is responsive, but you may need to log in.")
            except:
                pass
            
            print("It appears 'gemini' is not fully set up or requires login.")
            print("Would you like to open a terminal to set it up now? (You can close it after logging in)")
            choice = input("Open setup terminal? (Y/n): ").strip().lower()
            if choice != 'n':
                print("Launching setup terminal...")
                # Use start to open new window
                subprocess.Popen("start cmd /k gemini", shell=True)
                input("Press Enter here after you have completed login in the other window...")

    # 2. Ask for Windows Key Override
    print("\nDo you want Clippy to open when you press the Windows key?")
    print("(Note: This may require running as Administrator to work perfectly)")
    choice = input("Override Windows Key? (y/N): ").strip().lower() # Default N
    override = choice == 'y'
    
    # 3. Create Startup
    
    # 3. Create Startup
    print("\nAdding to Windows Startup...")
    try:
        create_startup_shortcut(script_path, python_exe, override)
        print("Success!")
    except Exception as e:
        print(f"Failed to create startup shortcut: {e}")
        
    print("\nInstallation Complete. You can run 'python clippy.py' to start it now.")

if __name__ == "__main__":
    main()
