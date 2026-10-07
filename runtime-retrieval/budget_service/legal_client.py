"""Use the existing PISTE service credentials; persist public responses only."""
import ast
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from .checks import fetch, as_json, CheckError


def client_headers(config_path=Path('/run/secrets/piste_config.py')):
    config = {}
    for node in ast.parse(config_path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    config[target.id] = node.value.value
    required = ('API_KEY', 'OAUTH_CLIENT_ID', 'OAUTH_CLIENT_SECRET')
    if not all(config.get(key) for key in required):
        raise CheckError('Configuration PISTE incomplète')
    encoded = base64.b64encode((config['OAUTH_CLIENT_ID'] + ':' + config['OAUTH_CLIENT_SECRET']).encode()).decode()
    raw, _, _ = fetch('https://oauth.piste.gouv.fr/api/oauth/token', data=b'grant_type=client_credentials', headers={'Authorization': 'Basic '+encoded, 'Content-Type': 'application/x-www-form-urlencoded'}, private=True)
    token = as_json(raw).get('access_token')
    if not token:
        raise CheckError('Jeton PISTE non reçu')
    return {'Authorization': 'Bearer '+token, 'X-Gravitee-Api-Key': config['API_KEY'], 'Content-Type': 'application/json'}


def collect(identifier, folder, headers):
    if not re.fullmatch(r'JORFTEXT\d{12}', identifier):
        raise ValueError('Identifiant JORF invalide')
    target = folder / (identifier + '.json')
    if target.exists():
        raw = target.read_bytes()
    else:
        raw, _, _ = fetch('https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/jorf', data=json.dumps({'textCid': identifier}).encode(), headers=headers, private=True)
        data = as_json(raw)
        if not data.get('title') or identifier not in json.dumps(data):
            raise CheckError('Contenu JORF attendu absent')
        folder.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {'id': identifier, 'title': as_json(raw).get('title'), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'checked_at': datetime.now(timezone.utc).isoformat(), 'url': 'https://www.legifrance.gouv.fr/jorf/id/'+identifier}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('identifiers', nargs='+')
    args = parser.parse_args()
    headers = client_headers()
    for identifier in args.identifiers:
        print(json.dumps(collect(identifier, args.out, headers), ensure_ascii=False))


if __name__ == '__main__':
    main()
