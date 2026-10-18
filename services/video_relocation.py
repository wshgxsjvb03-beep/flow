"""Automatically archive a completed hosted download, scoped to its exact project."""
import os
from pathlib import Path
import re
import shutil
import tempfile


def relocate_downloaded_video(project_path, target_path, download_roots):
    project = Path(project_path).resolve()
    target = Path(target_path).resolve()
    destination_dir = project / 'downloads' / 'videos'
    if (not project.is_dir() or not destination_dir.resolve().is_relative_to(project)
            or target.parent != destination_dir.resolve() or not re.fullmatch(r'\d+\.mp4', target.name, re.I)):
        return {'status': 'error', 'message': '目标视频不属于本项目 downloads/videos 目录'}
    if target.exists() and target.stat().st_size > 0:
        return {'status': 'already', 'target': str(target)}
    folder = re.sub(r'[\\/:*?"<>|]', '_', project.name).strip()
    candidates, searched = set(), []
    for root in download_roots:
        if not root:
            continue
        source_root = Path(root).resolve()
        source_dir = source_root / 'Flow' / folder
        source = source_dir / target.name
        searched.append(str(source))
        if (source_dir.resolve().is_relative_to(source_root) and source.is_file()
                and source.stat().st_size > 0 and source.resolve().parent == source_dir.resolve()):
            candidates.add(source.resolve())
    if not candidates:
        return {'status': 'missing', 'message': '尚未找到已下载文件', 'searched': searched}
    if len(candidates) > 1:
        return {'status': 'error', 'message': '发现多个同名下载文件，已保留源文件，请手动检查归位'}
    source = candidates.pop()
    temporary = None
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        before = source.stat()
        with source.open('rb') as incoming, tempfile.NamedTemporaryFile(
            dir=destination_dir, prefix='.relocating-', suffix='.part', delete=False
        ) as outgoing:
            temporary = Path(outgoing.name)
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or temporary.stat().st_size != after.st_size:
            return {'status': 'retry', 'message': '源文件仍在变化，稍后重试'}
        # Publish only a complete file, and never overwrite an existing target.
        # The temporary file is on the same volume as the destination.
        if os.name == 'nt':
            os.rename(temporary, target)  # Windows rename fails if target exists.
        else:
            os.link(temporary, target)
        try:
            source.unlink()
        except OSError as error:
            return {'status': 'moved', 'target': str(target), 'warning': f'视频已归位，源文件暂未移除：{error}'}
        return {'status': 'moved', 'target': str(target)}
    except FileExistsError:
        return {'status': 'already' if target.is_file() and target.stat().st_size > 0 else 'error',
                'target': str(target), 'message': '目标文件已存在，未覆盖'}
    except OSError as error:
        return {'status': 'retry', 'message': str(error)}
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
