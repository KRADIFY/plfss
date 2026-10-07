"""Copy only verified policy dossier PDFs into Budget's own data volume."""
import hashlib
import os
import shutil
from pathlib import Path
from . import topics


def main():
    data=Path(os.environ.get('BUDGET_DATA_DIR','/data')).resolve()
    inputs=Path('/inputs/dossiers/maprimerenov/sources').resolve()
    files=[]
    for source in topics.sources():
        target=(data/source['path']).resolve()
        origin=(inputs/target.name).resolve()
        if not target.is_relative_to(data/'topics/maprimerenov') or not origin.is_relative_to(inputs):
            raise ValueError('Chemin de source invalide')
        content=origin.read_bytes()
        if not content.startswith(b'%PDF-') or len(content)!=source['bytes'] or hashlib.sha256(content).hexdigest()!=source['sha256']:
            raise ValueError('Source PDF non conforme au registre : '+target.name)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Un fichier différent existe déjà : '+target.name)
        files.append((origin,target))
    for origin,target in files:
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix('.pdf.part')
            shutil.copyfile(origin,temporary)
            temporary.chmod(0o644)
            os.replace(temporary,target)
        print('Source vérifiée : '+target.name)


if __name__=='__main__':
    main()
