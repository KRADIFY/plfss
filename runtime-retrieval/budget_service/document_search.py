"""Public full-text search over a sanitized Nos Deniers document index."""
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3


SEARCH_DB = Path(os.environ.get('BUDGET_DOCUMENT_SEARCH_DB', '/data/derived/document-search.sqlite'))
ALLOWED_FORMATS = {'', 'pdf', 'csv', 'xls', 'xlsx', 'ods', 'html', 'xml', 'md'}
REQUIRED_TABLES = {'metadata', 'passages', 'citations', 'passages_fts'}


def connect(path=None):
    target = Path(path or SEARCH_DB).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    db = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def _metadata(db):
    return {row['key']: row['value'] for row in db.execute('SELECT key,value FROM metadata')}


def _number(meta, key):
    try:
        return int(meta.get(key, '0'))
    except (TypeError, ValueError):
        return 0


def status(path=None):
    target = Path(path or SEARCH_DB)
    if not target.is_file():
        return {
            'available': False,
            'state': 'preparing',
            'message': 'L’index du texte intégral est en cours de préparation. La recherche par titre reste disponible.',
        }
    try:
        with closing(connect(target)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            missing = sorted(REQUIRED_TABLES - tables)
            if missing:
                return {
                    'available': False,
                    'state': 'invalid',
                    'message': 'L’index documentaire publié est incomplet.',
                }
            meta = _metadata(db)
            ready = meta.get('state') == 'ready'
            return {
                'available': ready,
                'state': meta.get('state', 'invalid'),
                'message': meta.get('message') or (
                    'Recherche dans le texte intégral disponible.' if ready else 'L’index documentaire publié est incomplet.'
                ),
                'documents': _number(meta, 'document_count'),
                'passages': _number(meta, 'passage_count'),
                'generated_at': meta.get('generated_at', ''),
                'coverage': meta.get('coverage', ''),
                'version': meta.get('version', ''),
            }
    except (OSError, sqlite3.Error):
        return {
            'available': False,
            'state': 'invalid',
            'message': 'L’index du texte intégral est momentanément indisponible. La recherche par titre reste disponible.',
        }


def _value(query, key, default=''):
    value = query.get(key, [default])
    return value[0] if isinstance(value, list) else value


def parameters(query):
    raw = str(_value(query, 'q')).strip()
    if len(raw) > 200:
        raise ValueError('Recherche trop longue')
    year = str(_value(query, 'year')).strip()
    if year and (not year.isdigit() or not 1900 <= int(year) <= 2100):
        raise ValueError('Année invalide')
    fmt = str(_value(query, 'format')).strip().lower()
    if fmt not in ALLOWED_FORMATS:
        raise ValueError('Format invalide')
    try:
        limit = int(_value(query, 'limit', '40'))
    except (TypeError, ValueError):
        raise ValueError('Limite invalide') from None
    if not 1 <= limit <= 50:
        raise ValueError('Limite invalide')
    terms = re.findall(r'[^\W_]+', raw, flags=re.UNICODE)[:12]
    match = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
    return {'q': raw, 'year': year, 'format': fmt, 'limit': limit, 'match': match}


def search(query, path=None):
    p = parameters(query)
    info = status(path)
    response = dict(info, query=p['q'], count=0, items=[])
    if not info['available'] or not p['match']:
        return response
    with closing(connect(path)) as db:
        rows = db.execute(
            '''SELECT p.id,p.tokens,
                      snippet(passages_fts,1,'','',' … ',34) AS excerpt,
                      bm25(passages_fts) AS score
               FROM passages_fts
               JOIN passages p ON p.id=passages_fts.passage_id
              WHERE passages_fts MATCH ?
                AND EXISTS(
                    SELECT 1 FROM citations c
                     WHERE c.passage_id=p.id
                       AND (?='' OR c.format=?)
                       AND (?='' OR instr(c.years_key,'|' || ? || '|')>0)
                )
              ORDER BY score,p.id
              LIMIT ?''',
            (p['match'], p['format'], p['format'], p['year'], p['year'], p['limit']),
        ).fetchall()
        items = []
        citation_sql = '''SELECT source_id,title,url,locator,format,years_key,stage,source_kind,
                                 table_layout,numeric_status,local_available
                            FROM citations
                           WHERE passage_id=?
                             AND (?='' OR format=?)
                             AND (?='' OR instr(years_key,'|' || ? || '|')>0)
                           ORDER BY local_available DESC,title,locator
                           LIMIT 6'''
        for row in rows:
            citations = []
            for citation in db.execute(
                citation_sql,
                (row['id'], p['format'], p['format'], p['year'], p['year']),
            ):
                item = dict(citation)
                item['years'] = [int(year) for year in item.pop('years_key').strip('|').split('|') if year]
                item['local_available'] = bool(item['local_available'])
                citations.append(item)
            items.append({
                'id': row['id'],
                'excerpt': row['excerpt'].strip(),
                'tokens': row['tokens'],
                'citations': citations,
            })
        response['items'] = items
        response['count'] = len(items)
        return response
