# -*- coding: utf-8 -*-
"""Creates a desktop shortcut for Flow without a custom icon."""
import os
import sys
import subprocess

desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
app_dir = os.path.dirname(os.path.abspath(__file__))

ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{desktop}\\Flow.lnk")
$Shortcut.TargetPath = "pythonw"
$Shortcut.Arguments = "main.py"
$Shortcut.WorkingDirectory = "{app_dir}"
$Shortcut.Description = "Flow - AI视频批量制作"
$Shortcut.Save()
'''

result = subprocess.run(
    ["powershell", "-Command", ps_script],
    capture_output=True, text=True
)

if result.returncode == 0:
    print("[OK] Desktop shortcut created: " + desktop + "\\Flow.lnk")
else:
    print("[FAIL] " + result.stderr)
    sys.exit(1)
