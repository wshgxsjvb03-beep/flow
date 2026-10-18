"""Project-only prompt copies and stable sentence groups. Never writes app templates."""
import copy
import json
import os
import re
from pathlib import Path
import tempfile
import uuid


class ProjectPromptStore:
    FILE_NAME = 'project_prompt_edits.json'
    ID_FIELD = 'project_prompt_id'

    def __init__(self, project_dir):
        self.path = Path(project_dir) / self.FILE_NAME
        self.records = {}
        self.error = ''
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data.get('schema') != 1 or not isinstance(data.get('sentences'), dict):
                    raise ValueError('项目提示词文件格式不支持')
                if any(not isinstance(v, dict) for v in data['sentences'].values()):
                    raise ValueError('项目提示词记录损坏')
                if any(not isinstance(record[key], str) for record in data['sentences'].values()
                       for key in ('content', 'group', 'source_name') if key in record):
                    raise ValueError('项目提示词内容或分组不是文字')
                self.records = data['sentences']
            except Exception as error:
                self.error = str(error)

    def get(self, segment):
        return copy.deepcopy(self.records.get(segment.get(self.ID_FIELD), {}))

    def save(self, records):
        if self.error:
            raise ValueError(f'项目提示词文件无法读取，为避免覆盖已停止保存：{self.error}')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.project-prompts-', suffix='.tmp', delete=False) as output:
                temporary = output.name
                json.dump({'schema': 1, 'sentences': records}, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self.records = copy.deepcopy(records)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()

    def apply(self, model, updates):
        """Persist new stable IDs first; prompt content commits atomically afterwards.

        If content persistence fails, restore new IDs too, including IDs forked
        from duplicated sentences, so their previous project copies still resolve.
        """
        if self.error:
            raise ValueError(f'项目提示词文件无法读取：{self.error}')
        segments = model.spanish_segments
        counts = {}
        for segment in segments:
            key = segment.get(self.ID_FIELD)
            if key:
                counts[key] = counts.get(key, 0) + 1
        records = copy.deepcopy(self.records)
        new_ids = []
        for row, changes in updates.items():
            if not isinstance(row, int) or not 0 <= row < len(segments):
                raise ValueError('句子范围已经变化，请重新打开窗口')
            if not set(changes).issubset({'content', 'group', 'source_name'}):
                raise ValueError('无效的项目提示词字段')
        for row, changes in updates.items():
            segment = segments[row]
            previous = segment.get(self.ID_FIELD)
            record = self.get(segment)
            if not previous or counts.get(previous, 0) > 1:
                new_ids.append((segment, previous))
                segment[self.ID_FIELD] = uuid.uuid4().hex
            for key, value in changes.items():
                if value is None:
                    record.pop(key, None)
                else:
                    record[key] = value
            records[segment[self.ID_FIELD]] = record
        if new_ids and not model.save():
            for segment, previous in new_ids:
                if previous is None:
                    segment.pop(self.ID_FIELD, None)
                else:
                    segment[self.ID_FIELD] = previous
            raise OSError('项目句子标识未保存，提示词修改未应用')
        try:
            self.save(records)
        except (OSError, ValueError) as error:
            for segment, previous in new_ids:
                if previous is None:
                    segment.pop(self.ID_FIELD, None)
                else:
                    segment[self.ID_FIELD] = previous
            if new_ids and not model.save():
                raise OSError('提示词未保存，且句子标识回退失败；请保持项目打开并检查目录权限') from error
            raise


PROTECTED_TOKEN = re.compile(r'(\{spanish_text\}|\{camera_motion\})')


def common_prompt_source(sources):
    if not sources:
        raise ValueError('请先选中要编辑的句子')
    first = sources[0]
    if any((source.get('template_id'), source['content']) !=
           (first.get('template_id'), first['content']) for source in sources[1:]):
        raise ValueError('所选句子使用不同模板或不同修改版本，请选择相同模板的句子后再编辑')
    if '{spanish_text}' not in first['content']:
        raise ValueError('当前模板没有 {spanish_text} 文案占位符，无法安全编辑')
    return first


def plan_template_edit(sources, content):
    source = common_prompt_source(list(sources.values()))
    if PROTECTED_TOKEN.findall(content) != PROTECTED_TOKEN.findall(source['content']):
        raise ValueError('文案与运镜占位符不允许修改')
    return {row: {'content': content, 'source_name': source['name']}
            for row, original in sources.items() if original['content'] != content}
