"""Contract shared by the offline index builder and the read-only search service."""
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

VERSION = 'nos-deniers-retrieval-1'
MODEL = 'BAAI/bge-m3'
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
DIMENSION = 1024


def read_db(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if Path(str(path) + '-wal').exists() and Path(str(path) + '-wal').stat().st_size:
        raise ValueError('An immutable snapshot is required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    return db


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


def mentions_mpr(text):
    return bool(re.search(r"\b(?:ma[ ’']*prime[ ’']*renov|prime de transition energetique|mpr)\b", fold(text)))


def lexical_query(text, hybrid=False):
    if hybrid and mentions_mpr(text):
        # Keep the explicitly named scheme as an anchor, even in long questions.
        return '("MaPrimeRenov" OR "ma prime renov" OR "prime de transition énergétique" OR "MPR")'
    return query_terms(text, expand=True)


def query_terms(text, expand=False):
    tokens = re.findall(r'[^\W_]+', text, flags=re.UNICODE)[:24]
    stop = {'le','la','les','de','des','du','un','une','et','en','au','aux','pour','dans','sur','a','à','est','quel','quels','quelle','quelles'}
    tokens = [t for t in tokens if t.lower() not in stop]
    reserve = {'gel','gels','gelé','gelés','gelée','gelées','réserve','réserves','reserve','reserves'}
    phrases = []
    for token in tokens:
        if expand and token.lower() in reserve:
            phrases.append('("gel" OR "gels" OR "réserve" OR "surgel" OR "surgels" OR "dégel" OR "dégels" OR "indisponibilité")')
        elif expand and fold(token) == 'maprimerenov':
            phrases.append('("MaPrimeRénov" OR "prime de transition énergétique")')
        else:
            phrases.append('"' + token + '"')
    return ' AND '.join(phrases)
