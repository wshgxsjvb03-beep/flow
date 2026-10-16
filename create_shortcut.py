# -*- coding: utf-8 -*-
"""Creates a desktop shortcut for Flow口播工具 with logo.ico icon"""
import os
import sys
import subprocess

desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
app_dir = os.path.dirname(os.path.abspath(__file__))

ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{desktop}\\Flow口播工具.lnk")
$Shortcut.TargetPath = "pythonw"
$Shortcut.Arguments = "main.py"
$Shortcut.WorkingDirectory = "{app_dir}"
$Shortcut.IconLocation = "{app_dir}\\logo.ico"
$Shortcut.Description = "Flow口播工具 - AI视频批量制作"
$Shortcut.Save()
'''

result = subprocess.run(
    ["powershell", "-Command", ps_script],
    capture_output=True, text=True
)

if result.returncode == 0:
    print("[OK] Desktop shortcut created: " + desktop + "\\Flow口播工具.lnk")
    print("     Icon: " + app_dir + "\\logo.ico")
else:
    print("[FAIL] " + result.stderr)
    sys.exit(1)
