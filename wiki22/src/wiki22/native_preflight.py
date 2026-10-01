"""Negative-only syntactic preflight bound to the frozen native question parser.

This never authorizes an answer. It only avoids journal replay for shapes the
pinned parser cannot recognize. A different engine disables this optimization.
"""
import hashlib,re
from pathlib import Path
EXPECTED_ENGINE_SHA256 = 'fe62786669ed5e7bcd09b67b83b3fa4814c3686921346d3d90f313c8a00920e3'
_last_stamp=None
_matches=False

def possibly_native_question(query):
    global _last_stamp,_matches
    path=Path(__file__).with_name('native22_linguistic_guarded')/'language_engine.py'
    stat=path.stat();stamp=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    if stamp!=_last_stamp:
        _matches=hashlib.sha256(path.read_bytes()).hexdigest()==EXPECTED_ENGINE_SHA256;_last_stamp=stamp
    if not _matches:return True
    from .native22_linguistic_guarded.language_engine import spazi
    text=spazi(query).rstrip('? .')
    text=re.sub(r'\s+nel\s+\d{4}$','',text,flags=re.I)
    from .native22_linguistic_guarded.language_engine import Motore
    if Motore._advanced_shape(query) is not None:return True
    return any(re.fullmatch(p,text,re.I) for p in (
        r'(?:Qual|Chi) (?:è|era|fu)\s+(.+)',
        r'In quale paese è nat[oa]\s+(.+)',
        r'Dove è\s+(\w+)\s+(.+)',
        r'Chi\s+(\w+)\s+(.+)',
    ))
