# -*- coding: utf-8 -*-
import os
import re
import json
import threading
from pathlib import Path

class ConfigManager:
    """Manages application-wide settings in .app_config.json."""
    
    CONFIG_FILE_NAME = ".app_config.json"
    
    DEFAULT_MAX_BATCH_POINTS = 50
    DEFAULT_CHAR_DURATION_RULES = [
        {"max_chars": 40, "duration": 4},
        {"max_chars": 90, "duration": 6},
        {"max_chars": 130, "duration": 8},
        {"max_chars": 170, "duration": 10}
    ]
    DEFAULT_DURATION_POINTS_RULES = [
        {"duration": 4, "points": 7},
        {"duration": 6, "points": 10},
        {"duration": 8, "points": 12},
        {"duration": 10, "points": 15}
    ]
    
    DEFAULT_FORCED_SPLIT_MARKER = "///"
    
    # Speech extraction defaults
    DEFAULT_SPEECH_LANGUAGE = "es"  # Default: Spanish
    SUPPORTED_LANGUAGES = [
        ("es", "西班牙语 (Spanish)"),
        ("en", "英语 (English)"),
        ("zh", "中文 (Chinese)"),
        ("pt", "葡萄牙语 (Portuguese)"),
        ("fr", "法语 (French)"),
        ("de", "德语 (German)"),
        ("it", "意大利语 (Italian)"),
        ("ja", "日语 (Japanese)"),
        ("ko", "韩语 (Korean)"),
        ("ar", "阿拉伯语 (Arabic)"),
    ]
    
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.config_path = self.workspace_dir / self.CONFIG_FILE_NAME
        
        self.base_path = ""
        self.max_batch_points = self.DEFAULT_MAX_BATCH_POINTS
        self.forced_split_marker = self.DEFAULT_FORCED_SPLIT_MARKER
        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
        
        # Speech extraction settings
        self.gladia_api_keys = []      # List of Gladia API keys for round-robin
        self.elevenlabs_api_keys = []   # List of ElevenLabs API keys for round-robin
        self.speech_language = self.DEFAULT_SPEECH_LANGUAGE
        self._gladia_key_index = 0     # Current rotation index
        self._elevenlabs_key_index = 0 # Current rotation index
        self._key_lock = threading.Lock() # Thread lock for key rotation
        
        # Plugin server settings
        self.enable_plugin_server = True
        self.plugin_server_port = 18188
        
        # End frame settings
        self.DEFAULT_ENABLE_END_FRAME = False
        self.enable_end_frame = self.DEFAULT_ENABLE_END_FRAME
        
        self.load()

    def _load_dotenv(self):
        """Loads environment variables from .env in workspace_dir if present."""
        env_path = self.workspace_dir / ".env"
        if env_path.exists() and env_path.is_file():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception as e:
                print(f"Error reading .env file: {e}")

    def load(self):
        """Loads configuration from .app_config.json and .env."""
        self._load_dotenv()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.base_path = data.get("base_path", self.base_path)
                    self.max_batch_points = data.get("max_batch_points", self.DEFAULT_MAX_BATCH_POINTS)
                    self.forced_split_marker = data.get("forced_split_marker", self.DEFAULT_FORCED_SPLIT_MARKER)
                    
                    char_rules = data.get("char_duration_rules")
                    if char_rules and isinstance(char_rules, list):
                        self.char_duration_rules = char_rules
                    else:
                        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
                        
                    dur_rules = data.get("duration_points_rules")
                    if dur_rules and isinstance(dur_rules, list):
                        self.duration_points_rules = dur_rules
                    else:
                        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
                    
                    # Load speech extraction settings
                    self.gladia_api_keys = data.get("gladia_api_keys", [])
                    self.elevenlabs_api_keys = data.get("elevenlabs_api_keys", [])
                    self.speech_language = data.get("speech_language", self.DEFAULT_SPEECH_LANGUAGE)
                    
                    # Load plugin server settings
                    self.enable_plugin_server = data.get("enable_plugin_server", True)
                    self.plugin_server_port = data.get("plugin_server_port", 18188)
                    
                    # Load end frame setting
                    self.enable_end_frame = data.get("enable_end_frame", getattr(self, "DEFAULT_ENABLE_END_FRAME", False))
            except Exception as e:
                print(f"Error loading config: {e}")

        # Environment variables take precedence if set
        env_gladia = os.environ.get("GLADIA_API_KEYS")
        if env_gladia:
            self.gladia_api_keys = [k.strip() for k in re.split(r'[\n,]+', env_gladia) if k.strip()]

        env_eleven = os.environ.get("ELEVENLABS_API_KEYS")
        if env_eleven:
            self.elevenlabs_api_keys = [k.strip() for k in re.split(r'[\n,]+', env_eleven) if k.strip()]

    def save(self):
        """Saves current configuration to .app_config.json without losing existing keys."""
        data = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data.update({
            "base_path": self.base_path or data.get("base_path", ""),
            "max_batch_points": self.max_batch_points,
            "forced_split_marker": self.forced_split_marker,
            "char_duration_rules": self.char_duration_rules,
            "duration_points_rules": self.duration_points_rules,
            "gladia_api_keys": self.gladia_api_keys,
            "elevenlabs_api_keys": self.elevenlabs_api_keys,
            "speech_language": self.speech_language,
            "enable_plugin_server": self.enable_plugin_server,
            "plugin_server_port": self.plugin_server_port,
            "enable_end_frame": self.enable_end_frame
        })
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def reset_to_defaults(self):
        self.max_batch_points = self.DEFAULT_MAX_BATCH_POINTS
        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
        self.enable_end_frame = getattr(self, "DEFAULT_ENABLE_END_FRAME", False)
        self.save()

    def get_duration_for_length(self, length):
        """Calculates duration in seconds for a given character length."""
        sorted_rules = sorted(self.char_duration_rules, key=lambda x: x["max_chars"])
        for r in sorted_rules:
            if length <= r["max_chars"]:
                return r["duration"]
        if sorted_rules:
            return sorted_rules[-1]["duration"]
        return 10

    def get_duration_label(self, length):
        """Calculates duration label (e.g. '4s', '6s', '超时 (>10s)') for a length."""
        sorted_rules = sorted(self.char_duration_rules, key=lambda x: x["max_chars"])
        for r in sorted_rules:
            if length <= r["max_chars"]:
                return f"{r['duration']}s"
        if sorted_rules:
            max_dur = sorted_rules[-1]["duration"]
            return f"超时 (>{max_dur}s)"
        return "10s"

    def get_max_chars(self):
        """Returns the maximum character threshold defined in char_duration_rules."""
        if self.char_duration_rules:
            return max(r["max_chars"] for r in self.char_duration_rules)
        return 170

    def get_points_for_duration(self, duration):
        """Calculates points cost for a given duration in seconds."""
        for r in self.duration_points_rules:
            if r["duration"] == duration:
                return r["points"]
        return 7

    def get_next_gladia_key(self):
        """Returns the next Gladia API key using round-robin rotation.
        Returns None if no keys are configured."""
        with getattr(self, "_key_lock", threading.Lock()):
            if not self.gladia_api_keys:
                return None
            key = self.gladia_api_keys[self._gladia_key_index % len(self.gladia_api_keys)]
            self._gladia_key_index += 1
            return key

    def get_next_elevenlabs_key(self):
        """Returns the next ElevenLabs API key using round-robin rotation.
        Returns None if no keys are configured."""
        with getattr(self, "_key_lock", threading.Lock()):
            if not self.elevenlabs_api_keys:
                return None
            key = self.elevenlabs_api_keys[self._elevenlabs_key_index % len(self.elevenlabs_api_keys)]
            self._elevenlabs_key_index += 1
            return key

    def reset_key_rotation(self):
        """Resets the round-robin key rotation indices to 0."""
        with getattr(self, "_key_lock", threading.Lock()):
            self._gladia_key_index = 0
            self._elevenlabs_key_index = 0
