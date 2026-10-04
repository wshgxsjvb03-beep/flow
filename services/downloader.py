# -*- coding: utf-8 -*-
import os
import re
import shutil
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
import gdown

def ensure_unique_stems_in_dir(directory: Path) -> dict:
    """
    Scans directory and ensures that no two files share the same stem (filename without extension),
    even if their extensions/suffixes are different.
    If multiple files have the same stem (case-insensitive), renames subsequent ones to:
    {stem}_{counter}{suffix} (e.g. image.jpg, image_1.png, image_2.webp).
    Returns a dict mapping old_filename -> new_filename for any renamed files.
    """
    directory = Path(directory)
    if not directory.exists() or not directory.is_dir():
        return {}

    rename_map = {}
    try:
        files = [f for f in directory.iterdir() if f.is_file() and not f.name.endswith(".part")]
    except Exception:
        return {}

    # Sort files deterministically by mtime and name
    files.sort(key=lambda f: (f.stat().st_mtime, f.name))

    used_stems = set()
    for f in files:
        stem = f.stem
        stem_lower = stem.lower()
        suffix = f.suffix

        if stem_lower not in used_stems:
            used_stems.add(stem_lower)
        else:
            # Duplicate stem found! Even if suffix is different, base name cannot be the same!
            counter = 1
            while f"{stem}_{counter}".lower() in used_stems:
                counter += 1
            new_stem = f"{stem}_{counter}"
            new_name = f"{new_stem}{suffix}"
            new_path = f.with_name(new_name)
            try:
                f.rename(new_path)
                used_stems.add(new_stem.lower())
                rename_map[f.name] = new_name
            except Exception as e:
                print(f"Error renaming duplicate stem file {f.name} to {new_name}: {e}")

    return rename_map

class DownloadThread(QThread):
    """Asynchronous background thread for Google Drive downloading."""
    status_signal = pyqtSignal(str)  # Emits progress messages
    finished_signal = pyqtSignal(bool, str)  # Emits (success, message)

    def __init__(self, url, output_dir):
        super().__init__()
        # Split URLs by newline, spaces, or commas, and deduplicate while keeping order
        self.urls = []
        seen = set()
        for part in re.split(r'[\n\s,]+', url):
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                self.urls.append(cleaned)
        self.output_dir = Path(output_dir)
        self.allocated_stems = set()

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
            
            # Preload existing stems to prevent name collision across different extensions
            self.allocated_stems = set()
            for f in self.output_dir.iterdir():
                if f.is_file() and not f.name.endswith(".part"):
                    self.allocated_stems.add(f.stem.lower())

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
                    
                # 2. Security Check: Restrict strictly to Google Drive official domains
                import urllib.parse
                try:
                    parsed_url = urllib.parse.urlparse(url)
                    hostname = (parsed_url.hostname or "").lower()
                except Exception:
                    hostname = ""
                    
                allowed_drive_hosts = ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")
                if hostname not in allowed_drive_hosts and not hostname.endswith(".drive.google.com"):
                    fail_details.append(f"链接 #{idx+1} 拒绝下载: 安全拦截，只允许下载 Google Drive 官方域名资源。")
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
                                    target_file = (self.output_dir / item.path).resolve()
                                    if not target_file.is_relative_to(self.output_dir.resolve()):
                                        fail_details.append(f"链接 #{idx+1} 文件夹项安全拦截: 非法路径 {item.path}")
                                        continue
                                    # Direct download first (with duplicate check and unique stem logic)
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
                            # Fallback to standard gdown folder downloader with resume=True to avoid re-downloading
                            res = gdown.download_folder(
                                url=url,
                                output=str(self.output_dir),
                                quiet=True,
                                use_cookies=False,
                                resume=True
                            )
                            if res is not None:
                                success_count += 1
                            else:
                                fail_details.append(f"链接 #{idx+1} (文件夹) 下载失败，可能权限未公开。")
                    else:
                        # For files, try direct download using requests first (highly robust, skips duplicates)
                        if file_id:
                            success, filename_or_err = self._download_file_direct(file_id)
                            if success:
                                success_count += 1
                                continue
                            else:
                                fail_reason = filename_or_err
                        else:
                            fail_reason = "未能解析出文件 ID"
                            
                        # If direct download fails, fallback to gdown with resume=True
                        self.status_signal.emit(f"直接下载链接 #{idx+1} 失败 ({fail_reason})，尝试备用 gdown 模式...")
                        res = gdown.download(
                            url=url,
                            output=str(self.output_dir) + "/",
                            quiet=True,
                            fuzzy=True,
                            use_cookies=True,
                            resume=True
                        )
                        if res:
                            success_count += 1
                        else:
                            fail_details.append(f"链接 #{idx+1} (文件) 下载失败: {fail_reason}")
                except Exception as e:
                    fail_details.append(f"链接 #{idx+1} 报错: {str(e)}")
            
            # Post-download enforcement: guarantee no duplicate stems across all files even if extensions differ
            ensure_unique_stems_in_dir(self.output_dir)

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
        """Downloads a public Google Drive file directly using requests, bypassing gdown HTML scraping.
        Skips already downloaded files and ensures unique base names even if extensions differ.
        """
        import requests
        import urllib.parse
        
        url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        try:
            response = session.get(url, params={'id': file_id}, stream=True, timeout=(15, 120))
            
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
                response = session.get(url, params=params, stream=True, timeout=(15, 120))
                
            if response.status_code != 200:
                return False, f"HTTP 状态码 {response.status_code}"

            content_length = None
            try:
                cl_header = response.headers.get('Content-Length')
                if cl_header:
                    content_length = int(cl_header)
            except Exception:
                pass
                
            if target_path:
                dest_path = Path(target_path)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                # Check if already downloaded and valid
                if dest_path.exists() and dest_path.stat().st_size > 0:
                    if content_length is None or dest_path.stat().st_size == content_length:
                        self.status_signal.emit(f"文件已存在且完整，跳过重复下载: {dest_path.name}")
                        self.allocated_stems.add(dest_path.stem.lower())
                        return True, str(dest_path)
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
                if not filename or filename in ('.', '..'):
                    filename = f"file_{file_id}"
                
                stem = Path(filename).stem
                suffix = Path(filename).suffix

                # Check if exact file already exists and is complete in output_dir
                existing_candidate = self.output_dir / filename
                if existing_candidate.exists() and existing_candidate.stat().st_size > 0:
                    if content_length is None or existing_candidate.stat().st_size == content_length:
                        self.status_signal.emit(f"文件已存在且完整，跳过重复下载: {filename}")
                        self.allocated_stems.add(stem.lower())
                        return True, str(existing_candidate)

                # Enforce unique stem: "即便后缀不同，名字也不能一样"
                if stem.lower() in self.allocated_stems:
                    counter = 1
                    while f"{stem}_{counter}".lower() in self.allocated_stems:
                        counter += 1
                    stem = f"{stem}_{counter}"
                    filename = f"{stem}{suffix}"

                self.allocated_stems.add(stem.lower())
                dest_path = (self.output_dir / filename).resolve()
                if not dest_path.is_relative_to(self.output_dir.resolve()):
                    dest_path = self.output_dir / f"file_{file_id}_{stem}{suffix}"
            
            # Write to a temporary .part file first to prevent corrupted files on interruption
            CHUNK_SIZE = 32768
            temp_path = dest_path.with_name(f"{dest_path.name}.part")
            try:
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                if dest_path.exists():
                    dest_path.unlink()
                shutil.move(str(temp_path), str(dest_path))
            except Exception as write_err:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                raise write_err
                        
            return True, str(dest_path)
            
        except Exception as e:
            return False, str(e)

