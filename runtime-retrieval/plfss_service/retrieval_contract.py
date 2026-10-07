"""Pinned Nos Deniers encoding contract, independent PLFSS search generation."""
import hashlib,json,sqlite3
from pathlib import Path
VERSION='plfss-retrieval-1'
MODEL='BAAI/bge-m3'
REVISION='5617a9f61b028005a4858fdac845db406aefb181'
DIMENSION=1024
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read_db(path):
 p=Path(path).resolve()
 if not p.is_file():raise FileNotFoundError(p)
 if Path(str(p)+'-wal').exists() and Path(str(p)+'-wal').stat().st_size:raise ValueError('Immutable index required')
 db=sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True);db.row_factory=sqlite3.Row;return db
def write_json(path,value):
 p=Path(path);tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
