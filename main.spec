# Compatibility entry point; flow.spec is the maintained build definition.
from pathlib import Path
exec(compile(Path('flow.spec').read_text(encoding='utf-8'), 'flow.spec', 'exec'))
