# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path

class TemplateManager:
    """Manages prompt templates and camera motion presets in the app root directory."""
    
    TEMPLATES_FILE = "prompt_templates.json"
    MOTIONS_FILE = "camera_motions.json"
    
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.templates_path = self.workspace_dir / self.TEMPLATES_FILE
        self.motions_path = self.workspace_dir / self.MOTIONS_FILE
        
        self.templates = []
        self.motions = []
        
        self.load_all()

    def load_all(self):
        self.load_templates()
        self.load_motions()

    def load_templates(self):
        """Loads prompt templates from file. Initializes defaults or example if missing."""
        if self.templates_path.exists():
            try:
                with open(self.templates_path, "r", encoding="utf-8") as f:
                    self.templates = json.load(f)
                if not self.templates:
                    self.init_default_templates()
            except Exception as e:
                print(f"Error loading templates: {e}")
                self.init_default_templates()
        else:
            example_path = self.workspace_dir / "prompt_templates.example.json"
            if example_path.exists():
                try:
                    with open(example_path, "r", encoding="utf-8") as f:
                        self.templates = json.load(f)
                    if self.templates:
                        self.save_templates()
                    else:
                        self.init_default_templates()
                except Exception as e:
                    print(f"Error loading example templates: {e}")
                    self.init_default_templates()
            else:
                self.init_default_templates()

    def save_templates(self):
        """Saves prompt templates to file."""
        try:
            with open(self.templates_path, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving templates: {e}")
            return False

    def load_motions(self):
        """Loads camera motion presets. Initializes defaults or example if missing."""
        if self.motions_path.exists():
            try:
                with open(self.motions_path, "r", encoding="utf-8") as f:
                    self.motions = json.load(f)
                if not self.motions:
                    self.init_default_motions()
            except Exception as e:
                print(f"Error loading motions: {e}")
                self.init_default_motions()
        else:
            example_path = self.workspace_dir / "camera_motions.example.json"
            if example_path.exists():
                try:
                    with open(example_path, "r", encoding="utf-8") as f:
                        self.motions = json.load(f)
                    if self.motions:
                        self.save_motions()
                    else:
                        self.init_default_motions()
                except Exception as e:
                    print(f"Error loading example motions: {e}")
                    self.init_default_motions()
            else:
                self.init_default_motions()

    def save_motions(self):
        """Saves camera motion presets to file."""
        try:
            with open(self.motions_path, "w", encoding="utf-8") as f:
                json.dump(self.motions, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving motions: {e}")
            return False

    def init_default_templates(self):
        """Creates the default prompt templates."""
        self.templates = [
            {
                "id": "tpl_stage",
                "name": "舞台类",
                "content": (
                    "视频不要穿帮，人物站在讲台上讲道,电子屏幕的人物和讲台的人说话嘴型保持一致"
                    "（绝对不能在屏幕上出现两个同样的人物）人物手部有大浮度动作,动作铿锵有力."
                    "人物可以在讲台上来回走动.人物富有强烈感情的用西班牙语说：“{spanish_text}”"
                    "（话要说完整说准确,富有强烈感情，铿锵有力。） {camera_motion}。"
                    "镜头运动时不模糊虚化. 人物眼部： \"Subtle flickering "
                    "of eyelashes\"（睫毛微颤）。 人物超真实皮肤毛孔、强烈的面部微表情。 "
                    "现代 4K 数字电影质感，超清晰锐利对焦。极度纯净的镜头，无胶片颗粒，无漏光，"
                    "无闪烁。鲜艳自然的色彩，高清晰度。 没有背景音乐.有环境音效(观众的掌声、"
                    "欢呼声、喊阿门的声音). 话筒一直在人物手上拿着.禁止出现两个话筒.禁止话筒"
                    "悬在半空中,禁止出现第三只手.禁止话筒突然消失，禁止人物穿过讲台。"
                )
            },
            {
                "id": "tpl_closed_eyes",
                "name": "闭眼祷告",
                "content": (
                    "人物紧闭双眼，禁止改变人物的手部动作，人物说话富有感情，说：“{spanish_text}”"
                    "（话要说完整说准确，说的有感情。） {camera_motion} 侧面镜头，镜头可以稳定"
                    "线性轨道相机运动特写人物侧脸，但不要模糊虚化.不叠化。 人物眼部： \"Subtle flickering of eyelashes\""
                    "（睫毛微颤）。 人物超真实皮肤毛孔、面部微表情。 现代 4K 数字电影质感，"
                    "超清晰锐利对焦。极度纯净的镜头，无胶片颗粒，无漏光，无闪烁。鲜艳自然的色彩，"
                    "高清晰度。禁止改变人物的手部动作，交错的手指保持静止且坚硬。一直保持图片"
                    "中手的姿势不变动，不要放下手。"
                )
            },
            {
                "id": "tpl_general",
                "name": "普通类",
                "content": (
                    "视频不要穿帮，这个人物面部表情自然，微笑、和蔼一点声音干净自然的音频，"
                    "没有电子噪音，没有机器人声音，没有合成音，没有失真，逼真的录音效果，"
                    "用西班牙语说，下面所有的都要张口说包括数字：“{spanish_text}” {camera_motion}。"
                    "背景不要改变，但是还是可以有运动镜头的，面部微表情要自然。现代4K数字电影质感,超清晰锐利对焦。"
                    "极度纯净的镜头,无胶片颗粒, 无漏光,无闪烁。鲜艳自然的色彩,高清晰度。 "
                    "禁止添加字幕，禁止背景音乐. 禁止手上出现戒指，禁止头上出现天主教的小圆帽，"
                    "禁止随意添加单词或者句子，禁止漏掉单词或句子，和给的原文保持一致。禁止出现"
                    "第三只手。禁止手里的东西撒手、悬空。禁止皱眉头。"
                )
            },
            {
                "id": "tpl_walking",
                "name": "走路类",
                "content": (
                    "禁止改变图中人物的形象和装饰品，人物缓缓往前走，镜头缓缓向后移动，"
                    "人物面带笑容的看着镜头说话，禁止皱眉头，有一些手部动作，有感情的说：“{spanish_text}”"
                    "（话要说完整说准确，说的有感情。） {camera_motion}。不加转场,不模糊虚化.不叠化。 "
                    "人物眼部： \"Subtle flickering of eyelashes\"（睫毛微颤）。 "
                    "人物超真实皮肤毛孔、强烈的面部微表情。 现代 4K 数字电影质感，超清晰锐利对焦。"
                    "极度纯净的镜头，无胶片颗粒，无漏光，无闪烁。鲜艳自然的色彩，高清晰度。"
                )
            }
        ]
        self.save_templates()

    def init_default_motions(self):
        """Creates default camera motion presets."""
        self.motions = [
            {
                "id": "motion_default",
                "name": "带镜头运动 (默认)",
                "content": "带镜头运动，镜头多角度多景别，但运动幅度不要太大, 真实摄影机拍摄"
            },
            {
                "id": "motion_fixed",
                "name": "固定一镜到底",
                "content": "固定镜头，不要有景别切换，不要运动镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_panning",
                "name": "摇移镜头",
                "content": "可以加一些摇移镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_variations",
                "name": "微幅镜头变化",
                "content": "镜头可以有一些变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_slow_push",
                "name": "慢速推进镜头",
                "content": "镜头可以有一些慢速推进的变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_fast_push",
                "name": "快速推进镜头",
                "content": "镜头加个快速推进，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_closeup",
                "name": "特写镜头切换",
                "content": "镜头可以切特写，真实摄影机拍摄"
            },
            {
                "id": "motion_smooth_zoom",
                "name": "平滑运镜 (含缩放)",
                "content": "镜头多角度多景别，平滑运镜，加些缩放镜头，真实摄影机拍摄"
            },
            {
                "id": "motion_fixed_minor_pan",
                "name": "固定微平移推进",
                "content": "固定镜头，镜头可以有一些轻微左右推进的变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_oral_breathing",
                "name": "【口播类】轻微手持呼吸感",
                "content": "轻微手持相机微幅抖动，自然的呼吸感，主体面部微表情清晰稳定，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_oral_dolly_zoom",
                "name": "【口播类】滑动变焦一镜到底",
                "content": "慢速滑动变焦(Dolly Zoom)，背景轻微透视压缩但人物保持清晰居中，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_stage_tracking",
                "name": "【舞台类】横向追踪摇镜",
                "content": "镜头缓慢水平横向平移，追踪舞台上演讲者走动，保持讲台和人在画面内，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_stage_medium_close",
                "name": "【舞台类】中景到特写缓推",
                "content": "镜头缓慢从中景推进到紧凑的特写，捕捉演讲者肢体手势与情绪，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_prayer_linear",
                "name": "【闭眼祷告类】线性轨道平移",
                "content": "稳定线性轨道相机水平移动，特写人物侧脸，保持双手和交错的手指静止，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_walking_follow",
                "name": "【走路类】人物前移镜头后退",
                "content": "人物缓缓往前走，镜头缓缓向后移动追踪，人物面带笑容看着镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            }
        ]
        self.save_motions()

    def get_template(self, tpl_id):
        for t in self.templates:
            if t["id"] == tpl_id:
                return t
        return None

    def get_motion(self, motion_id):
        for m in self.motions:
            if m["id"] == motion_id:
                return m
        return None
