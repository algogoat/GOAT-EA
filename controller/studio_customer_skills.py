"""Discover the portable workflow skills shipped with this controller."""
import hashlib
from pathlib import Path
import re

NAMES=('goat-optimize','goat-template-create','goat-seed-research',
       'goat-portfolio-build','goat-repair-report','goat-observation-audit')


def customer_skills():
    root=Path(__file__).resolve().parent
    result=[]
    for name in NAMES:
        relative=f'skills/{name}/SKILL.md'
        file=root/relative
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('Customer skill escapes installed controller')
        raw=file.read_bytes();text=raw.decode('utf-8-sig')
        match=re.match(r'\A---\r?\nname: ([a-z0-9-]+)\r?\ndescription: ([^\r\n]+)\r?\n---\r?\n',text)
        if not match or match[1]!=name:
            raise ValueError('Customer skill metadata differs from its installed identity')
        result.append(dict(name=name,description=match[2],path=str(file.resolve()),
                           relative_path=relative,sha256=hashlib.sha256(raw).hexdigest()))
    return result
