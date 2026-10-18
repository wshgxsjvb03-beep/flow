"""Small, fail-closed boundaries for network and report input."""
from pathlib import Path
import os
import tempfile
from urllib.parse import urljoin, urlsplit


def https_host_allowed(url, hosts, subdomains=False):
    try:
        if not isinstance(url, str) or any(ord(c) < 32 for c in url):
            return False
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None
                and not parsed.fragment
                and any(host == name or (subdomains and host.endswith('.' + name))
                        for name in hosts))
    except (TypeError, ValueError):
        return False


def get_with_checked_redirects(session, url, allowed, **kwargs):
    """Validate *before* each request; requests must not follow redirects itself."""
    for _ in range(6):
        if not allowed(url):
            raise ValueError('下载或重定向地址不受信任')
        response = session.get(url, allow_redirects=False, **kwargs)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get('Location')
        response.close()
        if not location:
            raise ValueError('重定向缺少目标地址')
        url = urljoin(url, location)
    raise ValueError('重定向次数超出限制')


def report_video_path(project, value):
    """Reports can only name MP4 files inside this project's video directory."""
    project = Path(project).resolve()
    root = (project / 'downloads' / 'videos').resolve()
    if not root.is_relative_to(project):
        raise ValueError('视频目录超出当前项目')
    target = Path(value).resolve()
    if target.suffix.lower() != '.mp4' or not target.is_relative_to(root):
        raise ValueError('报告目标必须是当前项目 videos 目录下的 MP4 文件')
    return target


def project_image_path(project, name):
    """Metadata may reference only a plain image filename in project/downloads."""
    if (not isinstance(name, str) or not name or any(c in name for c in '/\\:')
            or any(ord(c) < 32 for c in name)):
        return None
    project = Path(project).resolve()
    root = (project / 'downloads').resolve()
    target = (root / name).resolve()
    if (not root.is_relative_to(project) or target.parent != root
            or target.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')):
        return None
    return target


def publish_video_chunks(project, target, chunks, max_bytes=256 * 1024 * 1024):
    """Publish a complete bounded MP4 without following a pre-created .part file."""
    target = report_video_path(project, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.report-', suffix='.part', delete=False) as output:
            temporary = Path(output.name)
            size = 0
            for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('视频超过大小上限')
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size <= 1024:
            raise ValueError('视频内容不完整')
        # Recheck directory/junction boundaries immediately before publishing.
        report_video_path(project, target)
        if os.name == 'nt':
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
        return target
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
