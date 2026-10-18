"""Prepare the three GitHub Release packages using only the standard library.

PyInstaller runs separately on GitHub's Windows and macOS runners. macOS
archives use ditto to preserve framework symlinks and executable permissions.
"""
import argparse
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import zipfile


PUBLIC_FILES = ('camera_motions.example.json', 'prompt_templates.example.json',
                '.app_config.example.json', '.env.example', 'LICENSE', 'LICENSE.LIST')


def validate_tag(tag):
    if not re.fullmatch(r'v[0-9][A-Za-z0-9._-]*', tag):
        raise ValueError('版本标签必须类似 v1.8.1，且不能包含路径或 shell 特殊字符')
    return tag


def extension_files(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    files = {'manifest.json'}
    background = manifest.get('background', {})
    if background.get('service_worker'):
        files.add(background['service_worker'])
    for entry in manifest.get('content_scripts', []):
        files.update(entry.get('js', []))
        files.update(entry.get('css', []))
    files.update(manifest.get('icons', {}).values())
    for key in ('default_icon', 'default_popup'):
        value = manifest.get('action', {}).get(key)
        if isinstance(value, dict):
            files.update(value.values())
        elif value:
            files.add(value)
    for entry in manifest.get('web_accessible_resources', []):
        for pattern in entry.get('resources', []):
            matches = list(directory.glob(pattern))
            if not matches:
                raise ValueError(f'扩展资源不存在: {pattern}')
            files.update(item.relative_to(directory).as_posix() for item in matches if item.is_file())
    if (directory / 'README.md').is_file():
        files.add('README.md')
    result = []
    for name in sorted(files):
        relative = Path(name)
        path = directory / relative
        if (relative.is_absolute() or '..' in relative.parts or
                not path.resolve().is_relative_to(directory) or not path.is_file()):
            raise ValueError(f'扩展资源路径无效或缺失: {name}')
        result.append((path, relative.as_posix()))
    return result


def package_extension(root, output, tag):
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'Flow-extension-{validate_tag(tag)}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path, name in extension_files(root / 'extension'):
            bundle.write(path, name)
    return archive


def prepare_desktop(root, platform):
    destination = root / 'dist' / ('Flow' if platform == 'windows' else 'Flow.app/Contents/Resources')
    if not destination.is_dir():
        raise FileNotFoundError(f'桌面构建目录不存在: {destination}')
    for name in PUBLIC_FILES:
        shutil.copy2(root / name, destination / name)
    for name in ('camera_motions', 'prompt_templates'):
        shutil.copy2(root / f'{name}.example.json', destination / f'{name}.json')
    if platform == 'macos':
        # BUNDLE adds PyInstaller's default icon even when EXE uses icon=NONE.
        # Remove it before the workflow signs the final bundle again.
        info = destination.parent / 'Info.plist'
        with info.open('rb') as incoming:
            data = plistlib.load(incoming)
        icon = data.pop('CFBundleIconFile', None)
        if icon:
            if Path(icon).name != icon:
                raise ValueError('应用图标路径无效')
            icon_path = destination / icon
            if icon_path.is_file():
                icon_path.unlink()
        with info.open('wb') as outgoing:
            plistlib.dump(data, outgoing)
    return destination


def package_windows(root, output, tag):
    prepare_desktop(root, 'windows')
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'Flow-windows-{validate_tag(tag)}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((root / 'dist' / 'Flow').rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(root / 'dist').as_posix())
    return archive


def collect_release(root, incoming, output, tag):
    tag = validate_tag(tag)
    output.mkdir(parents=True, exist_ok=True)
    for target in ('windows', 'extension'):
        name = f'Flow-{target}-{tag}.zip'
        shutil.copy2(incoming / name, output / name)
    macos = root / 'release-stage' / 'Flow-macos'
    for arch, folder in (('arm64', 'Apple Silicon'), ('x86_64', 'Intel')):
        destination = macos / folder
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ditto', '-x', '-k', str(incoming / f'Flow-macos-{arch}-{tag}.zip'),
                        str(destination)], check=True)
        if not (destination / 'Flow.app' / 'Contents' / 'MacOS' / 'Flow').is_file():
            raise FileNotFoundError(f'{arch} 的 Flow.app 不完整')
    archive = output / f'Flow-macos-{tag}.zip'
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(macos), str(archive)], check=True)
    expected = {f'Flow-{platform}-{tag}.zip' for platform in ('windows', 'macos', 'extension')}
    if {path.name for path in output.iterdir()} != expected:
        raise ValueError('Release 必须恰好包含 Windows、macOS、扩展三个压缩包')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('extension', 'windows', 'prepare-macos', 'collect'))
    parser.add_argument('--tag', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, default=Path('artifacts'))
    parser.add_argument('--incoming', type=Path, default=Path('incoming'))
    args = parser.parse_args()
    validate_tag(args.tag)
    if args.action == 'extension':
        print(package_extension(args.root, args.output, args.tag))
    elif args.action == 'windows':
        print(package_windows(args.root, args.output, args.tag))
    elif args.action == 'prepare-macos':
        prepare_desktop(args.root, 'macos')
    else:
        collect_release(args.root, args.incoming, args.output, args.tag)


if __name__ == '__main__':
    main()
