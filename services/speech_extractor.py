# -*- coding: utf-8 -*-
"""
Speech extraction service for extracting text from video files using
Gladia API or ElevenLabs API, with multi-key round-robin support.
"""
import time
import difflib
import requests
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal


class SpeechExtractor:
    """Handles speech-to-text extraction using Gladia or ElevenLabs APIs."""
    
    # Gladia API endpoints (v2)
    GLADIA_UPLOAD_URL = "https://api.gladia.io/v2/upload"
    GLADIA_TRANSCRIPTION_URL = "https://api.gladia.io/v2/pre-recorded"
    
    # ElevenLabs API endpoint
    ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
    
    # Polling config
    MAX_POLL_ATTEMPTS = 60
    POLL_INTERVAL_SECONDS = 3
    
    @staticmethod
    def extract_with_gladia(video_path, api_key, language="es"):
        """Extracts speech text from a video file using Gladia API v2.
        
        Steps:
        1. Upload file to get audio_url
        2. Submit transcription job
        3. Poll for result
        
        Returns:
            dict: {"success": bool, "text": str, "error": str}
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"success": False, "text": "", "error": f"文件不存在: {video_path}"}
        
        headers = {
            "x-gladia-key": api_key,
        }
        
        try:
            # Step 1: Upload file
            with open(video_path, "rb") as f:
                upload_response = requests.post(
                    SpeechExtractor.GLADIA_UPLOAD_URL,
                    headers=headers,
                    files={"audio": (video_path.name, f, "video/mp4")},
                    timeout=120
                )
            
            if upload_response.status_code != 200 and upload_response.status_code != 201:
                error_detail = ""
                try:
                    error_detail = upload_response.json().get("message", upload_response.text[:200])
                except Exception:
                    error_detail = upload_response.text[:200]
                return {
                    "success": False, "text": "",
                    "error": f"Gladia 上传失败 (HTTP {upload_response.status_code}): {error_detail}"
                }
            
            upload_data = upload_response.json()
            audio_url = upload_data.get("audio_url")
            if not audio_url:
                return {"success": False, "text": "", "error": "Gladia 上传返回结果中缺少 audio_url"}
            
            # Step 2: Submit transcription
            transcription_payload = {
                "audio_url": audio_url,
                "language": language,
            }
            
            trans_response = requests.post(
                SpeechExtractor.GLADIA_TRANSCRIPTION_URL,
                headers={**headers, "Content-Type": "application/json"},
                json=transcription_payload,
                timeout=30
            )
            
            if trans_response.status_code not in (200, 201):
                error_detail = ""
                try:
                    error_detail = trans_response.json().get("message", trans_response.text[:200])
                except Exception:
                    error_detail = trans_response.text[:200]
                return {
                    "success": False, "text": "",
                    "error": f"Gladia 转录请求失败 (HTTP {trans_response.status_code}): {error_detail}"
                }
            
            trans_data = trans_response.json()
            result_url = trans_data.get("result_url")
            if not result_url:
                return {"success": False, "text": "", "error": "Gladia 转录返回结果中缺少 result_url"}
            
            # Step 3: Poll for result
            for attempt in range(SpeechExtractor.MAX_POLL_ATTEMPTS):
                time.sleep(SpeechExtractor.POLL_INTERVAL_SECONDS)
                
                poll_response = requests.get(
                    result_url,
                    headers=headers,
                    timeout=30
                )
                
                if poll_response.status_code != 200:
                    continue
                
                poll_data = poll_response.json()
                status = poll_data.get("status", "")
                
                if status == "done":
                    # Extract full transcript
                    result = poll_data.get("result", {})
                    transcription = result.get("transcription", {})
                    full_transcript = transcription.get("full_transcript", "")
                    
                    if not full_transcript:
                        # Try alternative path in response
                        languages = transcription.get("languages", [])
                        if languages:
                            full_transcript = " ".join(
                                u.get("transcript", "") 
                                for u in transcription.get("utterances", [])
                            )
                    
                    return {"success": True, "text": full_transcript.strip(), "error": ""}
                
                elif status == "error":
                    error_msg = poll_data.get("error", {}).get("message", "未知错误")
                    return {"success": False, "text": "", "error": f"Gladia 转录失败: {error_msg}"}
            
            return {"success": False, "text": "", "error": "Gladia 转录超时 (轮询次数已达上限)"}
            
        except requests.exceptions.Timeout:
            return {"success": False, "text": "", "error": "Gladia 请求超时"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "text": "", "error": "Gladia 网络连接失败，请检查网络"}
        except Exception as e:
            return {"success": False, "text": "", "error": f"Gladia 提取异常: {str(e)}"}
    
    @staticmethod
    def extract_with_elevenlabs(video_path, api_key, language="es"):
        """Extracts speech text from a video file using ElevenLabs Speech-to-Text API.
        
        Returns:
            dict: {"success": bool, "text": str, "error": str}
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"success": False, "text": "", "error": f"文件不存在: {video_path}"}
        
        headers = {
            "xi-api-key": api_key,
        }
        
        try:
            with open(video_path, "rb") as f:
                files = {
                    "file": (video_path.name, f, "video/mp4"),
                }
                data = {
                    "model_id": "scribe_v1",
                    "language_code": language,
                }
                
                response = requests.post(
                    SpeechExtractor.ELEVENLABS_STT_URL,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=180
                )
            
            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "")
                if not text:
                    # Try alternative response format
                    text = result.get("transcription", "")
                return {"success": True, "text": text.strip(), "error": ""}
            
            elif response.status_code == 401:
                return {"success": False, "text": "", "error": "ElevenLabs API Key 无效或已过期"}
            elif response.status_code == 429:
                return {"success": False, "text": "", "error": "ElevenLabs API 请求频率超限，将尝试下一个 Key"}
            else:
                error_detail = ""
                try:
                    error_detail = response.json().get("detail", {})
                    if isinstance(error_detail, dict):
                        error_detail = error_detail.get("message", str(error_detail))
                    elif isinstance(error_detail, list):
                        error_detail = str(error_detail)
                except Exception:
                    error_detail = response.text[:200]
                return {
                    "success": False, "text": "",
                    "error": f"ElevenLabs 请求失败 (HTTP {response.status_code}): {error_detail}"
                }
        
        except requests.exceptions.Timeout:
            return {"success": False, "text": "", "error": "ElevenLabs 请求超时"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "text": "", "error": "ElevenLabs 网络连接失败，请检查网络"}
        except Exception as e:
            return {"success": False, "text": "", "error": f"ElevenLabs 提取异常: {str(e)}"}
    
    @staticmethod
    def _normalize_word_for_compare(word):
        """Internal helper to clean a word for matching only (ignores punctuation, case, accents).
        Does NOT modify the original text data.
        """
        import re
        w = word.lower().strip()
        w = re.sub(r'[^\w]', '', w, flags=re.UNICODE)
        accent_map = str.maketrans({
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        })
        return w.translate(accent_map)

    @staticmethod
    def calculate_similarity(text1, text2):
        """Calculates the word-level similarity ratio between two texts in-memory,
        ignoring punctuation, case, and accents. Does not alter any original text data.
        
        Returns:
            float: Similarity score as a percentage (0-100).
        """
        if not text1 and not text2:
            return 100.0
        if not text1 or not text2:
            return 0.0
        
        words1 = [SpeechExtractor._normalize_word_for_compare(w) for w in text1.split() if SpeechExtractor._normalize_word_for_compare(w)]
        words2 = [SpeechExtractor._normalize_word_for_compare(w) for w in text2.split() if SpeechExtractor._normalize_word_for_compare(w)]
        
        if not words1 and not words2:
            return 100.0
        if not words1 or not words2:
            return 0.0
            
        ratio = difflib.SequenceMatcher(None, words1, words2).ratio()
        return round(ratio * 100, 1)
    
    @staticmethod
    def extract_with_retry(video_path, engine, config_manager, language="es", max_retries=3):
        """Extracts text with automatic key rotation on failure.
        
        Tries the next API key in round-robin rotation when:
        - API key is invalid (401)
        - Rate limit exceeded (429)
        - Any extraction error
        
        Args:
            video_path: Path to the video file
            engine: "gladia" or "elevenlabs"
            config_manager: ConfigManager instance for key rotation
            language: Language code (default "es")
            max_retries: Maximum number of keys to try
            
        Returns:
            dict: {"success": bool, "text": str, "error": str, "key_used": str}
        """
        if engine == "gladia":
            key_count = len(config_manager.gladia_api_keys)
            get_key_fn = config_manager.get_next_gladia_key
            extract_fn = SpeechExtractor.extract_with_gladia
        elif engine == "elevenlabs":
            key_count = len(config_manager.elevenlabs_api_keys)
            get_key_fn = config_manager.get_next_elevenlabs_key
            extract_fn = SpeechExtractor.extract_with_elevenlabs
        else:
            return {"success": False, "text": "", "error": f"不支持的引擎: {engine}", "key_used": ""}
        
        if key_count == 0:
            engine_name = "Gladia" if engine == "gladia" else "ElevenLabs"
            return {
                "success": False, "text": "",
                "error": f"未配置 {engine_name} API Key，请在规则设置中添加",
                "key_used": ""
            }
        
        retries = min(max_retries, key_count)
        last_error = ""
        
        for i in range(retries):
            api_key = get_key_fn()
            if not api_key:
                continue
            
            result = extract_fn(video_path, api_key, language)
            
            if result["success"]:
                result["key_used"] = api_key[:8] + "..."
                return result
            
            last_error = result.get("error", "未知错误")
            
            # If it's a rate limit or auth error, try next key
            if "超限" in last_error or "无效" in last_error or "过期" in last_error or "429" in last_error or "401" in last_error:
                continue
            else:
                # For other errors (network, timeout), don't retry with different key
                break
        
        return {"success": False, "text": "", "error": last_error, "key_used": ""}


class ExtractionWorker(QThread):
    """Background worker thread for batch speech extraction.
    
    Signals:
        progress(int, int, str): (current_index, total, status_message)
        segment_done(int, str, float): (segment_index, extracted_text, similarity_score)
        finished(int, int, list): (success_count, total_count, errors_list)
    """
    
    progress = pyqtSignal(int, int, str)
    segment_done = pyqtSignal(int, str, float)
    finished = pyqtSignal(int, int, list)
    
    def __init__(self, segments_to_process, engine, config_manager, language="es", parent=None):
        """
        Args:
            segments_to_process: list of dicts with keys:
                - "segment_index": int (0-based)
                - "video_path": str (absolute path to video file)
                - "original_text": str (original script text for similarity calc)
            engine: "gladia" or "elevenlabs"
            config_manager: ConfigManager instance
            language: Language code
        """
        super().__init__(parent)
        self.segments_to_process = segments_to_process
        self.engine = engine
        self.config_manager = config_manager
        self.language = language
        self._cancelled = False
    
    def cancel(self):
        """Requests cancellation of the extraction process."""
        self._cancelled = True
        self.requestInterruption()
    
    def stop(self):
        """Stops the worker thread safely."""
        self.cancel()
        if self.isRunning():
            self.quit()
            self.wait(2000)

    def run(self):
        """Main extraction loop - processes segments one by one."""
        total = len(self.segments_to_process)
        success_count = 0
        errors = []
        
        # Reset key rotation at start
        self.config_manager.reset_key_rotation()
        
        for i, seg_info in enumerate(self.segments_to_process):
            if self._cancelled or self.isInterruptionRequested():
                self.progress.emit(i, total, "⛔ 已取消提取")
                break
            
            seg_idx = seg_info["segment_index"]
            video_path = seg_info["video_path"]
            original_text = seg_info["original_text"]
            
            self.progress.emit(i + 1, total, f"正在提取第 {seg_idx + 1} 段...")
            
            result = SpeechExtractor.extract_with_retry(
                video_path, self.engine, self.config_manager, self.language
            )
            
            if result["success"]:
                extracted_text = result["text"]
                similarity = SpeechExtractor.calculate_similarity(original_text, extracted_text)
                self.segment_done.emit(seg_idx, extracted_text, similarity)
                success_count += 1
            else:
                error_msg = f"片段 {seg_idx + 1}: {result['error']}"
                errors.append(error_msg)
                self.segment_done.emit(seg_idx, "", 0.0)
        
        self.finished.emit(success_count, total, errors)
