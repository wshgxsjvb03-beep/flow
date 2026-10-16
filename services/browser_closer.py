# -*- coding: utf-8 -*-
"""
通过 Windows API 关闭指定 Chrome 账号（Profile）的浏览器窗口。

背景：多个 Chrome 用户（Profile）共用同一个 chrome.exe 进程，所以绝不能结束进程，
只能精确关闭属于该 Profile 的窗口。

定位方式（按优先级）：
1. 窗口标题形如 "Chrome_Profile 509_C:|Users|...|User Data"（多开工具设置的标题）
   → 解析出 Profile 目录与 User Data 路径 → 读取 Local State 得到该 Profile 登录的邮箱
   → 与插件上报的邮箱匹配。
2. 插件把唯一标记写进网页标题，若窗口标题包含该标记则直接定位（普通 Chrome 适用）。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import time
import logging

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_CLOSE = 0x0010

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

_PROFILE_TITLE_RE = re.compile(r"^Chrome_(.+?)_([A-Za-z]:\|.*)$")
_local_state_cache = {}   # user_data_dir -> (loaded_at, {profile_dir: email})


def _enum_windows():
    """Returns list of (hwnd, pid, title) for all top-level windows."""
    result = []

    def cb(hwnd, _lparam):
        try:
            n = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result.append((hwnd, pid.value, title))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return result


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _profile_emails(user_data_dir):
    """Reads Chrome 'Local State' → {profile_dir: email(lower)} (cached 30s)."""
    now = time.time()
    cached = _local_state_cache.get(user_data_dir)
    if cached and now - cached[0] < 30:
        return cached[1]
    mapping = {}
    try:
        path = os.path.join(user_data_dir, "Local State")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for pdir, info in (data.get("profile", {}).get("info_cache", {}) or {}).items():
            email = (info.get("user_name") or "").strip().lower()
            if email:
                mapping[pdir] = email
    except Exception as e:
        logger.warning(f"读取 Chrome Local State 失败 ({user_data_dir}): {e}")
    _local_state_cache[user_data_dir] = (now, mapping)
    return mapping


def list_profile_windows():
    """Returns list of dicts {hwnd, pid, profile_dir, user_data_dir, email} for windows titled 'Chrome_<Profile>_<UserData>'."""
    out = []
    for hwnd, pid, title in _enum_windows():
        m = _PROFILE_TITLE_RE.match(title or "")
        if not m or not user32.IsWindowVisible(hwnd):
            continue
        if not _class_name(hwnd).startswith("Chrome_WidgetWin"):
            continue
        profile_dir = m.group(1)
        user_data_dir = m.group(2).replace("|", "\\")
        email = _profile_emails(user_data_dir).get(profile_dir, "")
        out.append({"hwnd": hwnd, "pid": pid, "profile_dir": profile_dir,
                    "user_data_dir": user_data_dir, "email": email})
    return out


def _email_matches(reported, profile_email):
    """插件读取的邮箱可能把显示名拼在前面（如 'Video' + 'bgvideo001@gmail.com'），用结尾匹配。"""
    if not reported or not profile_email:
        return False
    r = reported.strip().lower()
    return r == profile_email or r.endswith(profile_email)


def find_windows_for_email(reported_email):
    """Returns (hwnds, profile_dir, profile_email) for the Chrome profile whose email best matches."""
    wins = list_profile_windows()
    best_email = ""
    for w in wins:
        if _email_matches(reported_email, w["email"]) and len(w["email"]) > len(best_email):
            best_email = w["email"]
    if not best_email:
        return [], None, None
    hits = [w for w in wins if w["email"] == best_email]
    return [w["hwnd"] for w in hits], hits[0]["profile_dir"], best_email


def find_windows_by_title_token(token):
    """Windows whose title contains the token written by the plugin."""
    if not token:
        return []
    return [hwnd for hwnd, pid, title in _enum_windows() if token in (title or "")]


def close_window(hwnd):
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def window_exists(hwnd):
    return bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd))

# --- New robust closing method using TCP connection PID mapping ---

def _get_pid_from_port(port):
    """Finds the process ID owning the given local TCP port."""
    import subprocess
    try:
        output = subprocess.check_output(['netstat', '-ano'], creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8', errors='ignore')
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == 'TCP':
                local_addr = parts[1]
                if local_addr.endswith(f':{port}'):
                    return int(parts[-1])
    except Exception as e:
        logger.error(f"netstat failed: {e}")
    return None

def _get_process_tree_ctypes():
    """Returns {pid: {'ppid': ppid, 'name': name}} for all processes."""
    TH32CS_SNAPPROCESS = 0x00000002
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)), ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]
    
    kernel32 = ctypes.windll.kernel32
    tree = {}
    hProcessSnap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if hProcessSnap == -1:
        return tree
    pe32 = PROCESSENTRY32()
    pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
    
    if kernel32.Process32First(hProcessSnap, ctypes.byref(pe32)):
        while True:
            tree[pe32.th32ProcessID] = {
                'ppid': pe32.th32ParentProcessID,
                'name': pe32.szExeFile.decode('utf-8', 'ignore')
            }
            if not kernel32.Process32Next(hProcessSnap, ctypes.byref(pe32)):
                break
    kernel32.CloseHandle(hProcessSnap)
    return tree

def _get_process_cmdline(pid):
    import subprocess
    try:
        pid_int = int(pid)
        args = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid_int}").CommandLine'
        ]
        out = subprocess.check_output(args, shell=False, creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8', 'ignore').strip()
        return out
    except Exception:
        return ""

def _find_main_browser_pid(start_pid, tree):
    """
    Climbs the process tree starting from start_pid.
    The Main Browser Process is identified as the first process that does NOT have '--type=' in its command line.
    """
    current_pid = start_pid
    while current_pid in tree:
        cmdline = _get_process_cmdline(current_pid)
        if cmdline and "--type=" not in cmdline:
            return current_pid, cmdline
        ppid = tree[current_pid]['ppid']
        if ppid in tree:
            current_pid = ppid
        else:
            break
    return start_pid, _get_process_cmdline(start_pid)

def get_browser_profile_by_port(port):
    """Returns the profile name/dir for the browser connected on the given port."""
    pid = _get_pid_from_port(port)
    if not pid:
        return "未知端口"
    tree = _get_process_tree_ctypes()
    main_pid, cmdline = _find_main_browser_pid(pid, tree)
    
    import re
    # Try to extract "--profile-directory=Profile 1" or --profile-directory="Profile 1"
    
    # 1. Matches: "--profile-directory=Profile 1" (Brave style)
    m_profile = re.search(r'"--profile-directory=([^"]+)"', cmdline)
    if not m_profile:
        # 2. Matches: --profile-directory="Profile 1" (Chrome style)
        m_profile = re.search(r'--profile-directory="([^"]+)"', cmdline)
    if not m_profile:
        # 3. Matches: --profile-directory=Profile1 (No spaces, no quotes)
        m_profile = re.search(r"--profile-directory=([^\s\"]+)", cmdline)
        
    if m_profile:
        return m_profile.group(1)
        
    # Try to extract --user-data-dir="C:\..."
    m_user = re.search(r'"--user-data-dir=([^"]+)"', cmdline)
    if not m_user:
        m_user = re.search(r'--user-data-dir="([^"]+)"', cmdline)
    if not m_user:
        m_user = re.search(r"--user-data-dir=([^\s\"]+)", cmdline)
    if m_user:
        path = m_user.group(1)
        return path.split('\\')[-1].split('/')[-1] # return just the last folder name
        
    return f"PID:{main_pid}"

def kill_browser_by_port(port):
    """
    Finds the Main Chrome/Browser process connected to this WebSocket port,
    and gracefully closes its top-level windows (simulating clicking the X button).
    This avoids crashing the browser session and avoids killing child profiles.
    Returns True if successfully sent close signals.
    """
    pid = _get_pid_from_port(port)
    if not pid:
        logger.warning(f"Could not find PID for port {port}")
        return False
        
    tree = _get_process_tree_ctypes()
    if pid not in tree:
        logger.warning(f"PID {pid} not found in process tree.")
        return False
        
    # Find the main browser process (the one without --type= in command line)
    main_pid, cmdline = _find_main_browser_pid(pid, tree)
    main_name = tree.get(main_pid, {}).get('name', 'Unknown')
    logger.info(f"Port {port} -> Main Browser Process {main_pid} ({main_name}). Sending graceful close...")
    
    try:
        import win32gui
        import win32con
        import win32process
        
        def callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd):
                _, w_pid = win32process.GetWindowThreadProcessId(hwnd)
                if w_pid == main_pid:
                    hwnds.append(hwnd)
            return True

        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        
        if not hwnds:
            logger.warning(f"No visible windows found for PID {main_pid}.")
            return False
            
        for hwnd in hwnds:
            logger.info(f"Sending WM_CLOSE to HWND {hwnd} (PID: {main_pid})")
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            
        return True
    except Exception as e:
        logger.error(f"Failed to gracefully close windows for process {main_pid}: {e}")
        return False
