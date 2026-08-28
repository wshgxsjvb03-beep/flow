# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
import gdown

class DownloadThread(QThread):
    """Asynchronous background thread for Google Drive downloading."""
    status_signal = pyqtSignal(str)  # Emits progress messages
    finished_signal = pyqtSignal(bool, str)  # Emits (success, message)

    def __init__(self, url, output_dir):
        super().__init__()
        # Split URLs by newline, spaces, or commas, and keep all non-empty parts for validation
        self.urls = []
        for part in re.split(r'[\n\s,]+', url):
            cleaned = part.strip()
            if cleaned:
                self.urls.append(cleaned)
        self.output_dir = Path(output_dir)

    def stop(self):
        """Stops the download thread safely."""
        self.requestInterruption()
        if self.isRunning():
            self.quit()
            self.wait(2000)

    def run(self):
        if not self.urls:
            self.finished_signal.emit(False, "未找到任何下载链接。")
            return
            
        try:
            self.status_signal.emit("正在初始化下载目录...")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            success_count = 0
            fail_details = []
            total = len(self.urls)
            
            for idx, url in enumerate(self.urls):
                if self.isInterruptionRequested():
                    self.status_signal.emit("⛔ 下载已取消")
                    break

                short_url = url[:40] + "..." if len(url) > 40 else url
                self.status_signal.emit(f"正在处理第 {idx+1}/{total} 个链接: {short_url}")
                
                # 1. Format Validation
                if not (url.startswith("http://") or url.startswith("https://")):
                    fail_details.append(f"链接 #{idx+1} 拒绝下载: 链接格式无效（必须以 http/https 开头）。")
                    continue
                    
                # 2. Security Check: Restrict to Google Drive domains
                if "drive.google.com" not in url and "docs.google.com" not in url:
                    fail_details.append(f"链接 #{idx+1} 拒绝下载: 安全拦截，只允许下载 Google Drive 链接。")
                    continue
                
                # 3. Parse Google Drive ID and distinguish file/folder
                file_id = None
                is_folder = False
                
                if "folders/" in url:
                    is_folder = True
                    match = re.search(r'folders/([a-zA-Z0-9-_]+)', url)
                    if match:
                        file_id = match.group(1)
                else:
                    match = re.search(r'file/d/([a-zA-Z0-9-_]+)', url)
                    if match:
                        file_id = match.group(1)
                    else:
                        match = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', url)
                        if match:
                            file_id = match.group(1)
                
                try:
                    if is_folder:
                        # For folders, first try retrieving file list using skip_download=True
                        folder_success = False
                        try:
                            self.status_signal.emit(f"正在获取文件夹内容列表...")
                            files = gdown.download_folder(
                                url=url,
                                output=str(self.output_dir),
                                quiet=True,
                                skip_download=True,
                                use_cookies=False
                            )
                            if files is not None and len(files) > 0:
                                folder_file_count = len(files)
                                folder_success_count = 0
                                for f_idx, item in enumerate(files):
                                    self.status_signal.emit(f"正在下载文件夹文件 ({f_idx+1}/{folder_file_count}): {item.path}")
                                    target_file = self.output_dir / item.path
                                    # Direct download first
                                    success, err_or_name = self._download_file_direct(item.id, target_path=target_file)
                                    if not success:
                                        # Fallback to gdown for this file
                                        res = gdown.download(
                                            id=item.id,
                                            output=str(target_file),
                                            quiet=True,
                                            fuzzy=True,
                                            use_cookies=True
                                        )
                                        success = bool(res)
                                    if success:
                                        folder_success_count += 1
                                
                                if folder_success_count == folder_file_count:
                                    success_count += 1
                                    folder_success = True
                                elif folder_success_count > 0:
                                    success_count += 1
                                    folder_success = True
                                    fail_details.append(f"链接 #{idx+1} (文件夹): 部分文件下载失败 ({folder_success_count}/{folder_file_count})。")
                        except Exception as fe:
                            self.status_signal.emit(f"解析文件夹元数据失败: {str(fe)}，尝试标准 gdown 模式...")
                        
                        if not folder_success:
                            # Fallback to standard gdown folder downloader
                            res = gdown.download_folder(
                                url=url,
                                output=str(self.output_dir),
                                quiet=True,
                                use_cookies=False
                            )
                            if res is not None:
                                success_count += 1
                            else:
                                fail_details.append(f"链接 #{idx+1} (文件夹) 下载失败，可能权限未公开。")
                    else:
                        # For files, try direct download using requests first (highly robust)
                        if file_id:
                            success, filename_or_err = self._download_file_direct(file_id)
                            if success:
                                success_count += 1
                                continue
                            else:
                                fail_reason = filename_or_err
                        else:
                            fail_reason = "未能解析出文件 ID"
                            
                        # If direct download fails, fallback to gdown
                        self.status_signal.emit(f"直接下载链接 #{idx+1} 失败 ({fail_reason})，尝试备用 gdown 模式...")
                        res = gdown.download(
                            url=url,
                            output=str(self.output_dir) + "/",
                            quiet=True,
                            fuzzy=True,
                            use_cookies=True
                        )
                        if res:
                            success_count += 1
                        else:
                            fail_details.append(f"链接 #{idx+1} (文件) 下载失败: {fail_reason}")
                except Exception as e:
                    fail_details.append(f"链接 #{idx+1} 报错: {str(e)}")
            
            if success_count == total:
                self.finished_signal.emit(True, f"成功下载了全部 {total} 个资源！")
            else:
                msg = f"资源下载未全部完成 ({success_count}/{total} 成功)。\n失败详情:\n" + "\n".join(fail_details)
                self.finished_signal.emit(success_count > 0, msg)
                
        except Exception as e:
            err_msg = str(e)
            print(f"Download thread error: {err_msg}")
            self.finished_signal.emit(False, f"下载线程异常: {err_msg}")

    def _download_file_direct(self, file_id, target_path=None):
        """Downloads a public Google Drive file directly using requests, bypassing gdown HTML scraping."""
        import requests
        import urllib.parse
        
        url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        try:
            response = session.get(url, params={'id': file_id}, stream=True)
            
            # Check for cookies token first
            token = None
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    token = value
                    break
                    
            # If not in cookies, check if the response content is HTML (indicating a warning page)
            content_type = response.headers.get('Content-Type', '')
            if not token and 'text/html' in content_type:
                try:
                    # Safe to read text since it is a small HTML warning page
                    html_content = response.text
                    match = re.search(r'confirm=([a-zA-Z0-9-_]+)', html_content)
                    if match:
                        token = match.group(1)
                except Exception:
                    pass
                    
            if token:
                params = {'id': file_id, 'confirm': token}
                response = session.get(url, params=params, stream=True)
                
            if response.status_code != 200:
                return False, f"HTTP 状态码 {response.status_code}"
                
            if target_path:
                dest_path = Path(target_path)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                # Get filename from headers
                filename = f"file_{file_id}"
                cd = response.headers.get('Content-Disposition')
                if cd:
                    # 1. Try RFC 5987 filename* first (URL-encoded UTF-8, most reliable for non-ASCII)
                    fname_star_match = re.findall(r"filename\*=UTF-8''([^;\s]+)", cd)
                    if fname_star_match:
                        filename = urllib.parse.unquote(fname_star_match[0])
                    else:
                        # 2. Fallback to standard filename="..." and fix Latin1 decoding issues
                        fname_match = re.findall(r'filename="([^"]+)"', cd)
                        if fname_match:
                            raw_name = fname_match[0]
                            try:
                                # Re-decode from latin1 (ISO-8859-1) to UTF-8 to support Chinese characters
                                filename = raw_name.encode('latin1').decode('utf-8')
                            except Exception:
                                filename = raw_name
                            
                # Clean and sanitize filename
                invalid_chars = '<>:"/\\|?*'
                filename = "".join(c for c in filename if c not in invalid_chars).strip()
                
                dest_path = self.output_dir / filename
            
            CHUNK_SIZE = 32768
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        
            return True, str(dest_path)
            
        except Exception as e:
            return False, str(e)

