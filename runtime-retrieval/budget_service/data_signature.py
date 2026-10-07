"""Bind a reconciliation report to the database and financial registries served."""
import hashlib
import time
from functools import lru_cache
from pathlib import Path


def _calculate(path):
    value=hashlib.sha256()
    with open(path,'rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):value.update(part)
    return value.hexdigest()


@lru_cache(maxsize=256)
def _digest(path, device, inode, size, modified_ns, changed_ns):
    return _calculate(path)


def digest(path):
    path=Path(path).resolve();info=path.stat()
    # tmpfs and some host mounts can give two rapid writes identical timestamps.
    # Do not cache recently modified files; deployed read-only files are stable.
    if max(info.st_mtime_ns,info.st_ctime_ns)>time.time_ns()-2_000_000_000:
        return _calculate(path)
    return _digest(str(path),info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def signature(database,registries=None):
    registries=Path(registries) if registries is not None else Path(__file__).parent/'data'
    return dict(version=1,database_sha256=digest(database),
        registries={p.name:digest(p) for p in sorted(registries.glob('*.json'))})
