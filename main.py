# -*- coding: utf-8 -*-
import sys
import os
import traceback

# Force PyInstaller static analysis to bundle third-party packages
import PIL
import bs4
import gdown
import requests

def get_workspace_dir():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir.endswith("Contents/MacOS"):
            return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))

# 用户设置文件（模板配置 / 规则设置 / 账号备注等）
USER_SETTINGS_FILES = [
    ".app_config.json",        # 规则设置、存储路径、API Key 等
    "prompt_templates.json",   # 模板配置
    "camera_motions.json",     # 运镜模板
    "account_aliases.json",    # 账号备注
    "account_monitor.json",    # 积分阈值
    "batch_templates.json",
    "hosted_mode.json",
    ".env",
]

def get_data_dir():
    """
    Flow 用户设置目录沿用历史路径 %APPDATA%\\Flow口播工具，兼容已有设置。
    与程序安装目录分离，重新安装 / 覆盖 / 卸载程序都不会丢失设置。
    首次使用时自动把程序目录中已有的设置迁移过来（已存在的文件不会被覆盖）。
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(base, "Flow口播工具")
    try:
        os.makedirs(data_dir, exist_ok=True)
        import shutil
        old_dir = get_workspace_dir()
        for name in USER_SETTINGS_FILES:
            dst = os.path.join(data_dir, name)
            if os.path.exists(dst):
                continue  # 用户已有设置，永不覆盖（升级安装不会丢失预设/规则）
            for src in (os.path.join(old_dir, name), os.path.join(old_dir, "_internal", name)):
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    if name == ".app_config.json":
                        import json
                        with open(dst, encoding="utf-8") as config_file:
                            config = json.load(config_file)
                        storage_path = config.get("base_path")
                        if storage_path and not os.path.isabs(storage_path):
                            config["base_path"] = os.path.abspath(os.path.join(old_dir, storage_path))
                            with open(dst, "w", encoding="utf-8") as config_file:
                                json.dump(config, config_file, indent=4, ensure_ascii=False)
                    break
            if not os.path.exists(dst) and name in ("prompt_templates.json", "camera_motions.json"):
                example = name.replace(".json", ".example.json")
                for source_dir in (old_dir, os.path.join(old_dir, "_internal"),
                                   getattr(sys, '_MEIPASS', old_dir)):
                    source = os.path.join(source_dir, example)
                    if os.path.isfile(source):
                        shutil.copy2(source, dst)
                        break
        return data_dir
    except Exception as e:
        log_error(f"无法使用用户设置目录 {data_dir}，回退到程序目录: {e}")
        return get_workspace_dir()

def log_error(err_str):
    try:
        ws = get_workspace_dir()
        log_path = os.path.join(ws, "error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(err_str + "\n\n")
    except Exception:
        pass

def handle_exception(exc_type, exc_value, exc_traceback):
    err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_error(err_str)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if not QApplication.instance():
            _app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "程序运行异常 (Error)",
            f"应用发生异常：\n\n{exc_value}\n\n详细日志已保存至 error.log"
        )
    except Exception:
        pass

sys.excepthook = handle_exception

def qt_message_handler(mode, context, message):
    if "Point size <= 0" in message:
        return
    if sys.stderr is not None:
        try:
            sys.stderr.write(f"{message}\n")
        except Exception:
            pass

def main():
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import qInstallMessageHandler
        from views.main_window import MainWindow

        qInstallMessageHandler(qt_message_handler)
        app = QApplication(sys.argv)
        app.setApplicationName('Flow')
        
        window = MainWindow(get_data_dir())
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)

if __name__ == "__main__":
    main()

