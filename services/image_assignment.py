"""Plan image assignments without reading images or changing project data."""
import re


def natural_image_key(name):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', name))


def parse_sentence_range(text, count):
    """Convert one-based sentence numbers/ranges to zero-based rows."""
    rows = set()
    text = re.sub(r'\s*([-~～—至])\s*', r'\1', text.strip())
    for part in re.split(r'[,，、;；\s]+', text):
        if not part:
            continue
        match = re.fullmatch(r'(\d+)(?:\s*[-~～—至]\s*(\d+))?', part)
        if not match:
            raise ValueError('请输入句号，如 1-8,12,15-20')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= count:
            raise ValueError(f'句号必须在 1-{count} 内，且范围起点不能大于终点')
        rows.update(range(start - 1, end))
    if not rows:
        raise ValueError('请填写要分配的句号')
    return sorted(rows)


def plan_image_assignment(segments, image_names, rows=None, *, end_frames=True, preserve=True,
                          cycle=False, priorities=None, overrides=None):
    names = list(dict.fromkeys(image_names))
    weights = []
    for name in names:
        level = (priorities or {}).get(name, 0)
        if not isinstance(level, int) or not 0 <= level <= 99:
            raise ValueError('优先级必须是 0-99 的整数')
        weights.append(level + 1)
    # Smooth weighted round robin: level zero participates normally, and equal
    # levels stay balanced. Higher levels get a larger share without fixed runs.
    images = []
    current = [0] * len(names)
    total = sum(weights)
    for _ in range(total):
        for i, weight in enumerate(weights):
            current[i] += weight
        chosen = max(range(len(names)), key=current.__getitem__)
        current[chosen] -= total
        images.append(names[chosen])
    overrides = overrides or {}
    targets = sorted(set(range(len(segments)) if rows is None else rows))
    if any(not isinstance(row, int) or row < 0 or row >= len(segments) for row in targets):
        raise ValueError('分句范围无效')
    if not images and not any(overrides.get(row) for row in targets):
        return [{'row': row, 'changes': {},
                 'image_name': segments[row].get('image_name', ''),
                 'end_image_name': segments[row].get('end_image_name', ''),
                 'status': '未勾选图片，保持原样'} for row in targets]
    cursor = 0
    assignments = []

    def next_image(anchor=''):
        nonlocal cursor
        if anchor:
            if cycle and images and anchor in images:
                for offset in range(len(images)):
                    if images[(cursor + offset) % len(images)] == anchor:
                        cursor += offset + 1
                        break
            elif anchor in images[cursor:]:
                cursor = images.index(anchor, cursor) + 1
            return anchor
        if cycle and images:
            result = images[cursor % len(images)]
            cursor += 1
            return result
        if cursor >= len(images):
            return ''
        result = images[cursor]
        cursor += 1
        return result

    runs = []
    for row in targets:
        if not runs or row != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(row)

    for run in runs:
        if end_frames:
            boundaries = []
            conflicts = set()
            for slot in range(len(run) + 1):
                left = segments[run[slot - 1]].get('end_image_name', '') if slot else ''
                right = segments[run[slot]].get('image_name', '') if slot < len(run) else ''
                fixed_left = overrides.get(run[slot - 1], {}).get('end_image_name', '') if slot else ''
                fixed_right = overrides.get(run[slot], {}).get('image_name', '') if slot < len(run) else ''
                anchor = fixed_right or fixed_left or ((right or left) if preserve else '')
                boundaries.append(next_image(anchor))
                if fixed_left and fixed_right and fixed_left != fixed_right:
                    conflicts.update((run[slot - 1], run[slot]))
                if preserve and left and right and left != right:
                    conflicts.update((run[slot - 1], run[slot]))
            proposed = [(row, boundaries[i], boundaries[i + 1]) for i, row in enumerate(run)]
        else:
            conflicts = set()
            proposed = [(row, next_image(overrides.get(row, {}).get('image_name', '') or
                                        (segments[row].get('image_name', '') if preserve else '')), '')
                        for row in run]

        for row, start, end in proposed:
            segment = segments[row]
            changes = {}
            if start and (end or not end_frames):
                for field, value in [('image_name', start)] + ([('end_image_name', end)] if end_frames else []):
                    if not (preserve and segment.get(field) and field not in overrides.get(row, {})) and segment.get(field, '') != value:
                        changes[field] = value
                status = '将分配' if changes else '保留已有设置'
                if overrides.get(row):
                    status += '；已指定图片'
            else:
                status = '图片不足，保持原样'
            if row in conflicts:
                status += '；已有首尾帧不衔接，保留不覆盖'
                # Incompatible explicit pins cannot be silently overridden.
                if any(overrides.get(r, {}).get('end_image_name') and
                       overrides.get(r + 1, {}).get('image_name') and
                       overrides[r]['end_image_name'] != overrides[r + 1]['image_name']
                       for r in (row - 1, row) if r in run and r + 1 in run):
                    changes = {}
                    status = '指定首尾帧冲突，请调整固定图片'
            assignments.append({
                'row': row, 'changes': changes,
                'image_name': changes.get('image_name', segment.get('image_name', '')),
                'end_image_name': changes.get('end_image_name', segment.get('end_image_name', '')),
                'status': status,
            })
    return assignments
