"""Import only the 2023 FdC/AdP forecasts published in the 2023 PAP table."""
import collections,hashlib,json,os,re,sqlite3
from pathlib import Path
from .model import cents,code
from .normalize import DATA,dict_rows,get,source_id
SOURCE_ID='21342e83b18e59c74d21'
SOURCE_SHA='7fd79acb9a205c65bb6268103840169608dd13d2c4f593d9ceae226a2d065129'
YEAR=2023
STAGE='FDC_PREVU'

def parse_rows(table,baseline,sid=SOURCE_ID):
    """Programme/title rows are additive; later multiannual forecasts are ignored."""
    seen=set();facts=[];plf=collections.defaultdict(int);expected=collections.defaultdict(int)
    for r in baseline:
        if r[0]==YEAR and r[1]=='PLF':expected[(r[3],r[4],r[6],r[2])]+=r[14]
    for line,row in table:
        b=str(get(row,'budget')).strip();m=code(get(row,'code_mission'));p=code(get(row,'code_programme'));t=code(get(row,'code_titre'))
        if b not in ('BG','BA','CAS','CCF') or not re.fullmatch(r'[A-Z]{2}',m) or not re.fullmatch(r'\d{3}',p) or t not in ('1','2','3','4','5','6','7'):
            raise ValueError(f'Invalid budget coordinates at source row {line}')
        key=(b,m,p,t)
        if key in seen:raise ValueError(f'Duplicate programme/title row: {key}')
        seen.add(key)
        ml=str(get(row,'mission')).strip();label=str(get(row,'programme')).strip()
        if not ml or not label:raise ValueError(f'Missing labels at source row {line}')
        for measure in ('AE','CP'):
            field='prevision_fdc_adp_2023_'+measure.lower()
            amount=cents(get(row,field));reference=cents(get(row,'plf_2023_'+measure.lower()))
            if amount is None or reference is None:raise ValueError(f'Missing 2023 amount at source row {line}')
            plf[(b,m,p,measure)]+=reference
            facts.append((YEAR,STAGE,measure,b,m,ml,p,label,'','','','','',t,amount,sid,line,field,0))
    checks=[]
    for key,value in sorted(plf.items()):
        prior=expected.get(key)
        checks.append(dict(budget=key[0],mission=key[1],program=key[2],measure=key[3],pap_plf_cents=value,existing_plf_cents=prior,passed=prior is not None and value==prior))
    if not checks or any(not c['passed'] for c in checks):raise ValueError('2023 PAP programmes do not reconcile to the existing PLF')
    return facts,checks

def parse_source(record,baseline):
    if source_id(record)!=SOURCE_ID or record['sha256']!=SOURCE_SHA:raise ValueError('Unreviewed 2023 forecast source')
    if hashlib.sha256((DATA/record['path']).read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('Source checksum differs')
    table=list(dict_rows(record))
    if len(table)!=415:raise ValueError('Unexpected source row count')
    return parse_rows(table,baseline)

def extend(importer):
    source=next((r for r in importer.manifest if source_id(r)==SOURCE_ID),None)
    if source is None:raise ValueError('The reviewed 2023 FdC/AdP source is required for reconstruction')
    if any(r[0]==YEAR and r[1]==STAGE for r in importer.facts):raise ValueError('2023 FdC/AdP forecasts already imported')
    facts,checks=parse_source(source,importer.facts)
    importer.facts.extend(facts);importer.used.add(SOURCE_ID)
    return checks

if __name__=='__main__':
    with sqlite3.connect((DATA/'derived/budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        record=json.loads(db.execute('select data from sources where id=?',(SOURCE_ID,)).fetchone()[0])
        rows,checks=parse_source(record,list(db.execute('select * from facts')))
    print(json.dumps(dict(facts=len(rows),programme_measure_checks=len(checks),all_checks_passed=all(c['passed'] for c in checks))))