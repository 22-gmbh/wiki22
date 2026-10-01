from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest().upper()


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


SENSITIVE = re.compile(r'(?i)(?:password|passwd|credential|secret|api[_-]?key|access[_-]?token|private[_-]?key|authorization)')
SAFE_NAME = re.compile(r'^[\w .:+/()\[\],-]{1,140}$', re.UNICODE)


def label(value: str) -> str:
    if SENSITIVE.search(value):
        return 'CAMPO_SENSIBILE'
    return value if SAFE_NAME.fullmatch(value) else 'NOME_NON_ESPOSTO'


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def files_hash(root: Path) -> dict[str, str]:
    """Only an already authorized controlled tree; does not follow symbolic links."""
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts}
