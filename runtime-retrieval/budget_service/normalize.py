"""Offline, reproducible import of selected original tables. Raw files stay intact."""
import csv
import hashlib
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from .model import norm, code, cents, budget_code, parts

DATA = Path(os.environ.get('BUDGET_DATA_DIR', '/data'))
INPUTS = Path(os.environ.get('BUDGET_INPUTS_DIR', '/inputs'))

def read_table(record):
    path = DATA / record['path']
    if record.get('format') == 'xls':
        import xlrd
        sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
        return [sheet.row_values(i) for i in range(sheet.nrows)]
    with path.open(encoding=record.get('encoding') or 'utf-8-sig', newline='') as file:
        return list(csv.reader(file, delimiter=record.get('delimiter') or ';'))

def column_key(value):
    value=re.sub(r'[Nn]\s*[-\u2212]\s*1', 'Nmoins1', str(value))
    value=re.sub(r'[Nn]\s*[+]\s*1', 'Nplus1', value)
    return norm(value)

def dict_rows(record):
    rows = read_table(record)
    headers = [column_key(h) for h in rows[0]]
    for line, row in enumerate(rows[1:], 2):
        yield line, {key: row[i] if i < len(row) else '' for i, key in enumerate(headers) if key}

def get(row, *keys):
    for key in keys:
        if column_key(key) in row and str(row[column_key(key)]).strip(): return row[column_key(key)]
    return ''

def source_id(record):
    """Preserve reviewed catalogue IDs; keep legacy path-derived IDs unchanged."""
    if 'id' in record:
        identifier = record['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{20}', identifier):
            raise ValueError('Identifiant explicite de source invalide')
        return identifier
    return hashlib.sha256(record['path'].encode()).hexdigest()[:20]


def validate_source_ids(manifest):
    identifiers = set(); paths = set()
    for record in manifest:
        identifier = source_id(record)
        if identifier in identifiers or record['path'] in paths:
            raise ValueError('Identifiant ou chemin de source dupliqué : ' + identifier)
        identifiers.add(identifier); paths.add(record['path'])


class Importer:
    def __init__(self, manifest):
        validate_source_ids(manifest)
        self.manifest = manifest
        self.facts = []
        self.labels = {}
        self.missions = {}
        self.program_missions = {}
        self.issues = []
        self.used = set()
        self.stats = defaultdict(int)

    def remember(self, year, kind, identifier, label):
        if identifier and label and not str(label).isspace():
            self.labels[(year, kind, code(identifier))] = str(label).strip()
            if kind == 'M': self.missions[norm(label)] = code(identifier)

    def label(self, year, kind, identifier):
        return self.labels.get((year, kind, code(identifier)), '')

    def nomenclatures(self):
        for r in self.manifest:
            title = r.get('title', '')
            if 'nomenclature' not in title.lower() or r.get('format') not in ('csv', 'xls'): continue
            if r.get('format') == 'xls' and title not in ('PLR2019-Nomenclature.xls', 'PLR2020-Nomenclature.xls'): continue
            match = re.search(r'20\d{2}', title)
            if not match: continue
            year = int(match[0])
            for _, row in dict_rows(r):
                kind = str(get(row, 'Type ligne')).strip().upper()
                key = get(row, 'code')
                label = get(row, 'Libelle')
                if kind in ('MSN', 'MISSION'): self.remember(year, 'M', key, label)
                if kind == 'PGM':
                    self.remember(year, 'P', key, label)
                    if get(row, 'Mission'): self.program_missions[(year, code(key))] = code(get(row, 'Mission'))
                if kind in ('ACT', 'SACT'): self.remember(year, 'A', key, label)
                if get(row, 'Code Programme'):
                    p = code(get(row, 'Code Programme'))
                    self.remember(year, 'P', p, get(row, 'Programme'))
                    self.remember(year, 'A', p + '-' + code(get(row, 'Code Action'), 2), get(row, 'Action'))
                    self.remember(year, 'M', get(row, 'Code Mission'), get(row, 'Mission'))
        # Labels in the actual dated tables take priority over nomenclature fallbacks.
        for r in self.manifest:
            if r.get('format') != 'csv': continue
            columns = {norm(c) for c in r.get('columns', [])}
            if not {'codemission', 'mission'}.issubset(columns): continue
            match = re.search(r'20\d{2}', r.get('title', '') + r.get('dataset_id', ''))
            if not match: continue
            year = int(match[0])
            for _, row in dict_rows(r):
                actual = get(row, 'Année RAP', 'Année LFI', 'Année PLF', 'Exercice')
                y = int(float(actual)) if actual else year
                mc = get(row, 'Code Mission'); ml = get(row, 'Mission')
                self.remember(y, 'M', mc, ml)
                self.remember(y, 'P', get(row, 'code_programme') or get(row, 'programme'), get(row, 'programme') if get(row, 'code_programme') else get(row, 'libelle_programme'))
        for r in self.manifest:
            if r.get('dataset_id') != 'nomenclature-par-destination-lfi-2023' or r.get('role') != 'complete_api_export': continue
            for _, row in dict_rows(r):
                identifier = code(get(row, 'code_programme_action_ou_sous_action'))
                p, a, s = parts(code(get(row, 'programme')).removeprefix('P'), identifier, '')
                kind = str(get(row, 'type_de_ligne'))
                if kind == 'Programme': self.remember(2023, 'P', identifier, get(row, 'libelle_complet'))
                elif '-' in identifier:
                    bits = identifier.split('-'); identifier = code(bits[0]) + '-' + '-'.join(code(b, 2) for b in bits[1:])
                    self.remember(2023, 'A', identifier, get(row, 'libelle_complet'))
                mission = str(get(row, 'mission'))
                if re.match(r'^M[A-Z]{2} ', mission): self.remember(2023, 'M', mission[1:3], mission[4:])

    def add(self, r, line, year, stage, measure, dims, value, field):
        amount = cents(value)
        if amount is None: return
        b, mc, ml, p, pl, a, al, s, sl, category, title = dims
        if not p or not re.fullmatch(r'\d{3}', p): raise ValueError(f'Invalid programme: {p} in {r.get("title")} row {line}')
        if not mc: mc = self.missions.get(norm(ml)) or self.program_missions.get((year, p)) or ('M' + hashlib.sha256(norm(ml).encode()).hexdigest()[:8])
        ml = ml or self.label(year, 'M', mc) or 'Mission ' + mc
        pl = pl or self.label(year, 'P', p) or 'Programme ' + p
        al = al or self.label(year, 'A', p + '-' + a) or ('Action ' + a if a else '')
        sl = sl or self.label(year, 'A', p + '-' + a + '-' + s) or ('Sous-action ' + s if s else '')
        sid = source_id(r)
        approximate = int(bool(re.search(r'[eE][+]?[0-9]+', str(value))))
        self.facts.append((year, stage, measure, b, mc, ml, p, pl, a, al, s, sl, category, title, amount, sid, line, field, approximate))
        self.used.add(sid); self.stats[f'{year}/{stage}/{b}'] += 1

    def standard_dims(self, row, year):
        coded_program = get(row, 'code_programme')
        p, a, s = parts(coded_program or get(row, 'programme'),
                        get(row, 'code_action') if coded_program else get(row, 'action'),
                        get(row, 'code_sous_action') if coded_program else get(row, 'sous_action', 'sousaction'))
        b = budget_code(get(row, 'type_de_budget_hors_budgets_annexes', 'type_de_budget', 'typebudget', 'type_mission', 'type_de_mission'))
        mc = get(row, 'code_mission'); ml = get(row, 'mission') if mc else get(row, 'libelle_mission')
        if not mc: mc = get(row, 'mission')
        return (b, code(mc), str(ml), p, str(get(row, 'programme') if coded_program else get(row, 'libelle_programme')),
                a, str(get(row, 'action') if coded_program else get(row, 'libelle_action')),
                s, str(get(row, 'sous_action') if coded_program else get(row, 'libelle_sousaction', 'libelle_sous_action')),
                code(get(row, 'code_categorie', 'categorie')), code(get(row, 'code_titre', 'titre')))

    def standard(self, r, year, stages, only_ba=False):
        for line, row in dict_rows(r):
            if not get(row, 'code_programme', 'programme'): continue
            dims = self.standard_dims(row, year)
            if only_ba and dims[0] != 'BA': continue
            for stage, mapping in stages.items():
                for measure, field in mapping.items():
                    if isinstance(field, list):
                        vals = [cents(get(row, f)) for f in field]
                        value = None if any(v is None for v in vals) else str(sum(vals) / 100)
                        field_name = ' + '.join(field)
                    else: value, field_name = get(row, field), field
                    self.add(r, line, year, stage, measure, dims, value, field_name)

    def legacy_2017(self, r):
        rows = read_table(r)
        b = 'BG' if '-BG-' in r['title'] else 'CAS' if '-CAS-' in r['title'] else 'CCF'
        offset = 0 if b == 'BG' else 1
        for line, row in enumerate(rows[1:], 2):
            if not row or not row[0]: continue
            p, a, s = parts(row[2+offset], row[4+offset], '')
            dims = (b, '', row[1+offset], p, row[3+offset], a, row[5+offset], s, '', code(row[6+offset]), code(row[6+offset])[:1])
            for stage, ae, cp in [('PLF',9,13),('LFI',11,15)]:
                self.add(r,line,2017,stage,'AE',dims,row[ae+offset],rows[0][ae+offset])
                self.add(r,line,2017,stage,'CP',dims,row[cp+offset],rows[0][cp+offset])

    def annex(self, r, year, measure):
        for line, row in dict_rows(r):
            program = str(get(row, 'Programme')).strip()
            match = re.match(r'^(.*)\s+-\s+(\d{3})$', program)
            if match:
                p, program_label = match[2], match[1]
            else:
                candidates = [(key[2], label) for key, label in self.labels.items() if key[0] == year and key[1] == 'P' and len(program) > 100 and norm(label).startswith(norm(program))]
                if len(candidates) != 1: raise ValueError(f'Unrecognised programme in annex {line}: {program}')
                p, program_label = candidates[0]
                self.issues.append({'kind':'truncated_program_label','source':source_id(r),'row':line,'program':p,'reason':'Code retrouvé par correspondance unique dans la nomenclature annuelle.'})
            b = 'BG' if r['title'].startswith('Annexe1') else budget_code(get(row, 'Categorie'))
            if not b: b = 'CAS' if p.startswith('7') else 'CCF'
            title = '2' if str(get(row, 'Titre')).startswith('Titre 2') else 'HT2'
            dims = (b, '', get(row,'Mission'), p, program_label, '', '', '', '', '', title)
            mapping = {'LFI':'LFI','OUVERT':f'Total_{measure}_' + ('Ouvertes' if measure=='AE' else 'Ouverts'),
                       'EXEC':'AE_Consommees' if measure=='AE' else 'Depenses_constatees',
                       'REPORT_ENTRANT':'Report_N-1','LEGIS':'LFR','REGLEMENT':'Mvts_reglementaires',
                       'FDC':'FDC_et_ADP','FONGIBILITE':'Fongibilite_asymetrique',
                       'PLRG_OUVERTURE':'Modif_Ouvertures','PLRG_ANNULATION':'Modif_Annulations','REPORT_SORTANT':'Report_N+1'}
            for stage, field in mapping.items():
                self.add(r,line,year,stage,measure,dims,get(row,field),field)
            # A direct, independent source identity checks the meaning of movement columns.
            opening = cents(get(row, mapping['OUVERT']))
            terms = [cents(get(row, mapping[k])) for k in ('LFI','REPORT_ENTRANT','LEGIS','REGLEMENT','FDC','FONGIBILITE')]
            if opening is not None and all(v is not None for v in terms) and abs(opening-sum(terms)) > 2:
                self.issues.append({'source':source_id(r),'row':line,'kind':'opening_identity','difference_cents':opening-sum(terms)})

    def import_tables(self):
        for r in self.manifest:
            title = r.get('title',''); ds = r.get('dataset_id','')
            api = r.get('role') == 'complete_api_export'
            if r.get('format') not in ('csv','xls'): continue
            if re.fullmatch(r'LFI2017-(BG|CAS|CCF)-Action_Categorie.csv',title): self.legacy_2017(r)
            elif title == 'LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv': self.standard(r,2018,{'LFI':{'AE':'AE LFI 2018','CP':'CP LFI 2018'}})
            elif 'PLF 2019' in title and 'axe nature.csv' in title: self.standard(r,2019,{'PLF':{'AE':'AE PLF 2019','CP':'CP PLF 2019'}})
            elif ds == 'loi-de-finances-initiale-pour-2019-lfi-2019-1' and api: self.standard(r,2019,{'LFI':{'AE':'ae_lfi_2019','CP':'cp_lfi_2019'}})
            elif title in ('PLF_2020_Credits.csv','PLF_2020_CreditsBa.csv'): self.standard(r,2020,{'PLF':{'AE':'aePlfNp1','CP':'cpPlfNp1'}})
            elif title == 'LFI2020-crédits.csv': self.standard(r,2020,{'LFI':{'AE':'AE LFI 2020','CP':'CP LFI 2020'}})
            elif title in ('LFI2021_crédits-AE_CP.csv','LFI2022_detaillee.csv'):
                y = int(re.search(r'20\d{2}',title)[0])
                self.standard(r,y,{'PLF':{'AE':['AE T2 PLF','AE HT2 PLF'],'CP':['CP T2 PLF','CP HT2 PLF']},'LFI':{'AE':'AE ( T2 + HT2) LFI','CP':'CP ( T2 + HT2) LFI'}})
            elif ds == 'plf-2023-credits_destination_nature' and api: self.standard(r,2023,{'PLF':{'AE':'ae','CP':'cp'}})
            elif ds in ('plf-2024-depenses-2024-selon-nomenclatures-destination-et-nature','plf25-depenses-2025-du-bg-et-des-ba-selon-nomenclatures-destination-et-nature') and api:
                y = 2024 if '2024' in ds else 2025
                self.standard(r,y,{'PLF':{'AE':'ae_plf','CP':'cp_plf'},'FDC_PREVU':{'AE':'ae_prev_fdc_adp','CP':'cp_prev_fdc_adp'}})
            elif ds == 'projet-de-loi-de-reglement-2019-plr-20190' and api:
                self.standard(r,2018,{'EXEC':{'AE':'exec_ae_2018_rap_2018','CP':'exec_cp_2018_rap_2018'}})
            elif title in ('PLR2019-Credits_Destination_Nature.xls','PLR2020-Credits_Destination_Nature.xls'):
                self.standard(r,int(title[3:7]),{'EXEC':{'AE':'AE EXEC','CP':'CP EXEC'}})
            elif 'PLR 2017' in title and 'par Mission en' in title:
                measure = 'AE' if 'en AE' in title else 'CP'
                self.standard(r,2017,{'EXEC':{measure:f'EXEC {measure} 2017 RAP 2017'}})
            elif re.fullmatch(r'Annexe[12]-Etat_(AE|CP)-202[345].csv',title):
                self.annex(r,int(title[-8:-4]),'AE' if '_AE-' in title else 'CP')
        self.issues.append({'kind':'excluded_source','source_dataset':'credits-ae-et-cp-votes-nomenclature-par-destination-et-nature-lfi-2023','reason':'Export avec colonnes LFI et titres uniformément égales à 4. Détail LFI écarté ; LFI par programme issu des annexes PLRG.'})

    def save(self):
        derived = DATA / 'derived'; derived.mkdir(exist_ok=True)
        target = derived / 'budget.sqlite'; temp = derived / 'budget.build.sqlite'
        from .normalize_validated import check_preserved, save_extra
        # Full reconstruction is supported only against a complete certified copy.
        # The bounded replay is not evidence of a complete import from an empty DB.
        if not target.exists():
            raise ValueError('Reconstruction vierge non certifiée : utiliser une copie complète de la base validée.')
        from .normalize_replay import extend as replay_reviewed
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro', uri=True)) as previous:
            previous_meta = {k: json.loads(v) for k, v in previous.execute('SELECT key,value FROM meta')}
            replay_reviewed(self, DATA, previous_meta=previous_meta)
            check_preserved(previous, self.facts)
        if temp.exists(): temp.unlink()
        db = sqlite3.connect(temp)
        db.execute('PRAGMA temp_store=MEMORY')
        db.executescript('''
        CREATE TABLE facts(year INTEGER,stage TEXT,measure TEXT,budget TEXT,mission TEXT,mission_label TEXT,
        program TEXT,program_label TEXT,action TEXT,action_label TEXT,subaction TEXT,subaction_label TEXT,
        category TEXT,title TEXT,cents INTEGER,source TEXT,line INTEGER,field TEXT,approximate INTEGER);
        CREATE TABLE sources(id TEXT PRIMARY KEY, data TEXT);
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
        ''')
        db.executemany('INSERT INTO facts VALUES('+','.join(['?']*19)+')',self.facts)
        save_extra(db, self)
        sources = []
        for r in self.manifest:
            obj = dict(r); obj['id']=source_id(r); obj['imported']=obj['id'] in self.used
            obj['title']=r.get('title') or r.get('dataset_title') or r.get('dataset_id') or Path(r['path']).name
            sources.append((obj['id'],json.dumps(obj,ensure_ascii=False)))
        db.executemany('INSERT INTO sources VALUES(?,?)',sources)
        indices={}; inflation_source=None
        for r in self.manifest:
            if r.get('format') == 'xml' and 'insee' in r['path']:
                root=ET.parse(DATA/r['path']).getroot()
                for node in root.iter():
                    if node.tag.endswith('Obs'): indices[int(node.attrib['TIME_PERIOD'])]=node.attrib['OBS_VALUE']
                inflation_source=source_id(r)
        meta={'version':'0.3','built_at':datetime.now(timezone.utc).isoformat(),'fact_count':len(self.facts),
              'source_count':len(sources),'imported_source_count':len(self.used),'issues':self.issues,
              'indices':indices,'inflation_source':inflation_source,'stats':dict(self.stats)}
        version_hash=hashlib.sha256()
        for fact in self.facts: version_hash.update(json.dumps(fact,ensure_ascii=False,separators=(',',':')).encode())
        version_hash.update(json.dumps(indices,sort_keys=True).encode())
        meta['data_version']=version_hash.hexdigest()
        meta['catalogue_updated_at']=meta['built_at']
        meta.update(self.replayed_meta)
        for k,v in meta.items(): db.execute('INSERT INTO meta VALUES(?,?)',(k,json.dumps(v,ensure_ascii=False)))
        db.executescript('CREATE INDEX scope ON facts(measure,budget,year,mission,program,action,subaction,stage); CREATE INDEX provenance ON facts(source,line);')
        db.commit()
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        db.close(); os.chmod(temp,0o644)
        if target.exists():
            backup=derived/'rebuild-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup.mkdir(parents=True,exist_ok=False)
            with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as previous, closing(sqlite3.connect(backup/'budget.sqlite')) as copy:
                previous.backup(copy)
        os.replace(temp,target)
        (derived/'normalization-report.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in meta.items() if k not in ('issues','stats')},ensure_ascii=False)); print('Issues:',len(self.issues))

def main():
    manifest=json.loads((INPUTS/'MANIFEST-COLLECTE.json').read_text(encoding='utf-8-sig'))
    from .normalize_more import extend
    importer=Importer(manifest); importer.nomenclatures(); importer.import_tables(); extend(importer)
    from .normalize_validated import extend as replay_validated
    replay_validated(importer); importer.save()

if __name__=='__main__': main()
