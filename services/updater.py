# -*- coding: utf-8 -*-
"""
在线检查更新 / 一键下载安装。

- 通过 GitHub Releases 公共 API 获取最新版本（无需 token）
- 下载 FlowCue-Setup-x.y.z.exe 到临时目录，校验大小与来源域名
- 以 /SILENT 方式启动安装包：安装程序会自动关闭本程序、覆盖安装并重新启动；
  用户设置保存在 %APPDATA%，不受影响。
"""
import os
import re
import sys
import tempfile
import subprocess
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from version import __version__, GITHUB_REPO

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ALLOWED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com")
SETUP_RE = re.compile(r"^FlowCue-Setup-.*\.exe$", re.IGNORECASE)


def parse_version(v):
    """'v1.2.3' -> (1, 2, 3)；无法解析的部分按 0 处理。"""
    nums = re.findall(r"\d+", str(v or ""))
    t = tuple(int(n) for n in nums[:4])
    return t + (0,) * (3 - len(t)) if len(t) < 3 else t


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def _host_allowed(url):
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_DOWNLOAD_HOSTS)
    except Exception:
        return False


class CheckUpdateThread(QThread):
    """结果: finished_signal(dict) —— {ok, error, has_update, version, notes, url, size, name}"""
    finished_signal = pyqtSignal(dict)

    def run(self):
        res = {"ok": False, "error": "", "has_update": False, "version": "", "notes": "",
               "url": "", "size": 0, "name": ""}
        try:
            r = requests.get(API_URL, timeout=15,
                             headers={"Accept": "application/vnd.github+json", "User-Agent": "FlowCue-Updater"})
            if r.status_code == 404:
                res["error"] = "未找到已发布的版本。"
            elif r.status_code != 200:
                res["error"] = f"GitHub 返回 HTTP {r.status_code}（可能是访问频率受限，请稍后再试）"
            else:
                data = r.json()
                tag = data.get("tag_name", "")
                res.update(ok=True, version=tag.lstrip("vV"), notes=data.get("body") or "")
                for a in data.get("assets", []):
                    if SETUP_RE.match(a.get("name", "")):
                        res.update(url=a.get("browser_download_url", ""), size=a.get("size", 0), name=a["name"])
                        break
                res["has_update"] = is_newer(tag) and bool(res["url"])
                if is_newer(tag) and not res["url"]:
                    res["error"] = "发现新版本，但发布页没有安装包（FlowCue-Setup-*.exe）。"
        except Exception as e:
            res["error"] = f"检查更新失败：{e}"
        self.finished_signal.emit(res)


class DownloadUpdateThread(QThread):
    progress_signal = pyqtSignal(int, int)      # downloaded, total
    finished_signal = pyqtSignal(bool, str)     # success, path_or_error

    def __init__(self, url, name, expected_size=0):
        super().__init__()
        self.url, self.name, self.expected_size = url, name, expected_size

    def run(self):
        if not _host_allowed(self.url):
            self.finished_signal.emit(False, "下载地址不在允许的域名范围内，已拒绝。")
            return
        dest_dir = os.path.join(tempfile.gettempdir(), "FlowCue_update")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(self.name))
        part = dest + ".part"
        try:
            with requests.get(self.url, stream=True, timeout=30,
                              headers={"User-Agent": "FlowCue-Updater"}) as r:
                r.raise_for_status()
                if not _host_allowed(r.url):
                    raise RuntimeError("重定向到了不允许的域名")
                total = int(r.headers.get("Content-Length") or self.expected_size or 0)
                done = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_content(256 * 1024):
                        if self.isInterruptionRequested():
                            raise RuntimeError("已取消")
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            self.progress_signal.emit(done, total)
            if self.expected_size and os.path.getsize(part) != self.expected_size:
                raise RuntimeError("下载文件大小与发布页不一致，文件可能损坏")
            os.replace(part, dest)
            self.finished_signal.emit(True, dest)
        except Exception as e:
            try:
                os.remove(part)
            except OSError:
                pass
            self.finished_signal.emit(False, f"下载失败：{e}")


def launch_installer(path):
    """启动安装包（静默覆盖安装，完成后自动重启软件）。调用后应立即退出本程序。"""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
