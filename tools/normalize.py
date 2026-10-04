"""Extraction vérifiable des tableaux normatifs ; autres cellules conservées en inventaire."""
import hashlib,json,re,sqlite3,sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
import lxml.html
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plfss_service.model import norm,amount,stage_for,branch,ondam
DATA=ROOT/'data'


def clean(value):return re.sub(r'\s+',' ',str(value or '')).strip()
def texts(node):return clean(' '.join(node.itertext()))
def years(text):return [int(y) for y in re.findall(r'(?<!\d)20\d\d(?!\d)',text)]
def exercise(context):
    matches=re.findall(r'(?:année|annee|exercice|pour|en|titre de l’année|titre de l\x27année)\s*[^0-9]{0,15}(20\d\d)',context,re.I)
    return int(matches[-1]) if matches else None


def header_metric(text):
    n=norm(text)
    if n in ('recettes','previsionsderecettes','previsionderecettes'):return 'RECETTES'
    if n in ('depenses','objectifsdedepenses','objectifdedepenses','previsionsdedepenses'):return 'DEPENSES'
    if n=='solde':return 'SOLDE'
    return None

def amount_like(text):
    try:return amount(text,1) is not None
    except Exception:return False


def scope(context):
    # Several successive tables share an article. The nearest explicit heading
    # wins, rather than a mention in the heading of the previous table.
    n=norm(context)
    rg=n.rfind('regimegeneral')
    robss=max(n.rfind('ensembledesregimesobligatoires'),n.rfind('ensembledesregimesdebase'))
    if rg<0 and robss<0:robss=n.rfind('regimesobligatoires')
    return 'RG' if rg>robss else ('ROBSS' if robss>=0 else None)


def table_facts(node,source,edition,kind):
    result=[];inventory=[]
    tables=node.xpath('//table')
    for ti,table in enumerate(tables):
        if table.xpath('.//table'):
            inventory.append(dict(source=source['id'],table=ti,status='layout_container',recognized_facts=0))
            continue
        rows=[[texts(c) for c in tr.xpath('./th|./td')] for tr in table.xpath('.//tr')]
        before=table.xpath('preceding::p[position()<=6]')
        context=clean(' '.join(texts(p) for p in before))
        if not context:context=texts(node)[:1800]
        unittext=norm(' '.join(' '.join(r) for r in rows[:4])+' '+context[-1000:])
        unit=1_000_000_000 if 'milliard' in unittext or 'mdeur' in unittext else (1_000_000 if 'million' in unittext else None)
        headers=[];hi=None
        for ri,row in enumerate(rows[:6]):
            mapped=[header_metric(c) for c in row]
            if all(k in mapped for k in ('RECETTES','DEPENSES','SOLDE')):headers=mapped;hi=ri;break
        y=exercise(context)
        perimeter=scope(context+' '+(' '.join(rows[0]) if rows else ''))
        captured=0
        def add(entity,metric,value,ri,ci,year,label,column,priority=100):
            nonlocal captured
            if year is None or not 2017<=year<=2027:return
            target_scope='FSV' if entity=='FSV' else ((perimeter+'_FSV') if entity=='TOTAL_FSV' and perimeter else perimeter)
            if target_scope is None:return
            try:cents=amount(value,unit)
            except Exception:return
            if cents is None:return
            # A published zero is retained with the same source locator as any other value.
            places=len(str(value).split(',')[-1]) if ',' in str(value) else (len(str(value).split('.')[-1]) if '.' in str(value) else 0)
            quantum=Decimal(unit)/(10**places)
            result.append(dict(exercise=year,edition=edition,kind=kind,stage=stage_for(kind,edition,year),
                domain='ONDAM' if metric=='ONDAM' else 'EQUILIBRE',perimeter=target_scope,entity=entity,
                metric='DEPENSES' if metric=='ONDAM' else metric,amount_cents=cents,raw=value,unit_eur=unit,
                precision_eur=str(quantum),source_id=source['id'],source_sha=source['sha256'],table_index=ti,
                row_index=ri,column_index=ci,row_label=label,column_label=column,context=context[-1200:],priority=priority))
            captured+=1
        if unit and hi is not None:
            for ri,row in enumerate(rows[hi+1:],hi+1):
                if len(row)!=len(headers):continue
                entity=branch(row[0])
                if not entity:continue
                for ci,metric in enumerate(headers):
                    if metric:add(entity,metric,row[ci],ri,ci,y,row[0],rows[hi][ci])
        elif unit and any('sousobjectif' in norm(c) for r in rows[:5] for c in r):
            for ri,row in enumerate(rows):
                if len(row)==2:
                    entity=ondam(row[0])
                    if entity:add(entity,'ONDAM',row[1],ri,1,y,row[0],'Objectif de dépenses')
        elif unit:
            # Annex tables carry several exercises. The heading of each column determines the year.
            yr=None;yr_index=None
            for ri,row in enumerate(rows[:7]):
                mapped=[years(c)[0] if len(years(c))==1 else None for c in row]
                if sum(v is not None for v in mapped)>=2:yr=mapped;yr_index=ri;break
            if yr:
                entity=None
                # Article annexes contain successive RG, ROBSS, FSV and
                # combined tables. Only the nearest actual heading owns this
                # grid: an FSV mention in the previous grid must not leak.
                headings=[texts(p) for p in before if scope(texts(p)) or 'fondssolidaritevieillesse' in norm(texts(p)) or 'fondsdesolidaritevieillesse' in norm(texts(p))]
                heading=headings[-1] if headings else context
                title=norm(heading)
                stated_scope=scope(heading)
                if stated_scope:perimeter=stated_scope
                if 'fondssolidaritevieillesse' in title or 'fondsdesolidaritevieillesse' in title:entity='TOTAL_FSV' if stated_scope else 'FSV'
                year_columns=[(ci,year) for ci,year in enumerate(yr) if year]
                entity_label=heading
                balance_row=yr_index+1
                entity_row=None
                for ri,row in enumerate(rows[yr_index+1:],yr_index+1):
                    if not row:continue
                    label=row[0];label_norm=norm(label)
                    row_scope=scope(label)
                    if label_norm.startswith('robss'):row_scope='ROBSS'
                    elif label_norm.startswith('rg'):row_scope='RG'
                    metric_cells=[ci for ci,c in enumerate(row) if header_metric(c)]
                    if row_scope:perimeter=row_scope
                    detected=branch(label)
                    if row_scope and ('fsv' in label_norm or 'fondsdesolidaritevieillesse' in label_norm):detected='TOTAL_FSV'
                    elif label_norm in ('rgconsolide','robssconsolide'):detected='TOTAL'
                    if detected:entity=detected;entity_label=label;balance_row=ri;entity_row=ri
                    if not metric_cells:
                        if row_scope and not detected:entity=None
                        elif not detected and not any(amount_like(c) for c in row[1:]):entity=None
                        continue
                    if len(metric_cells)!=1 or not entity:continue
                    metric_ci=metric_cells[0];metric=header_metric(row[metric_ci])
                    # Word-generated HTML omits the entity cell on the second
                    # and third row of a rowspan. Colspans can also be purely
                    # presentational. Align the ordered numeric cells with the
                    # ordered years; retain the ORIGINAL physical locator.
                    numeric=[(ci,c) for ci,c in enumerate(row) if ci>metric_ci and amount_like(c)]
                    if len(numeric)!=len(year_columns):continue
                    for (ci,value),(header_ci,year) in zip(numeric,year_columns):
                        previous=len(result)
                        add(entity,metric,value,ri,ci,year,entity_label,rows[yr_index][header_ci],priority=50)
                        if len(result)>previous:
                            result[-1].update(balance_row_index=balance_row,
                                entity_row_index=entity_row,year_header_row_index=yr_index,
                                year_header_column_index=header_ci,metric_column_index=metric_ci)
        inventory.append(dict(source=source['id'],table=ti,rows=len(rows),recognized_facts=captured,
                              status='normalized' if captured else 'other_table_or_requires_qualification',context=context[-800:]))
    return result,inventory


def main():
    sources=json.loads((DATA/'catalogue/documents.json').read_text(encoding='utf-8'))
    original=json.loads((DATA/'catalogue/lfss-moulineuse.json').read_text(encoding='utf-8-sig'))
    facts=[];tables=[];generated=[]
    for article in original['articles']:
        if not article.get('html'):continue
        edition=years(article['title'])[-1]
        content=article['html'].encode('utf-8')
        sid=article['id'];target=DATA/'documents'/str(edition)/(sid+'.html')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        source=dict(id=sid,title=article['title']+' — article '+str(article.get('num') or 'annexe'),
                    url='https://www.legifrance.gouv.fr/jorf/article_jo/'+sid,publication_year=edition,
                    family='LFSS promulguée',kind='moulineuse_journal_officiel',status='downloaded',
                    path=target.relative_to(DATA).as_posix(),sha256=hashlib.sha256(content).hexdigest(),bytes=len(content),
                    article=article.get('num'),text_id=article['text_id'],publication_date=article['publication_date'],
                    evidence='Article JORF original, récupéré par Moulineuse depuis legifrance.article ; identifiant et contenu conservés')
        generated.append(source)
        # JORF fragments have no charset declaration. Passing UTF-8 bytes to
        # libxml's default HTML parser would corrupt accented table headers.
        doc=lxml.html.fromstring(article['html'])
        fs,ts=table_facts(doc,source,edition,'LFSS');facts.extend(fs);tables.extend(ts)
    # Only first-deposit AN projects feed "Proposé"; later parliamentary readings stay documentary.
    projects=json.loads((DATA/'catalogue/an-projects.json').read_text(encoding='utf-8-sig'))
    first={}
    for p in projects:
        if not p['uid'].startswith('PRJLAN') or not p['deposit_date']:continue
        y=years(p['title'])[-1]
        if y not in first or p['deposit_date']<first[y]['deposit_date']:first[y]=p
    for s in sources:
        if s['status']!='downloaded' or not s.get('path','').endswith(('.html','.htm','.asp')):continue
        year=s['publication_year']
        p=first.get(year)
        historical_initial=(year==2017 and s['url']=='https://www.assemblee-nationale.fr/14/projets/pl4072.asp')
        if not historical_initial and (not p or p['uid'] not in s['url']):continue
        doc=lxml.html.fromstring((DATA/s['path']).read_bytes())
        fs,ts=table_facts(doc,s,year,'PLFSS');facts.extend(fs);tables.extend(ts)
    excel=DATA/'extracted/excel-facts.json'
    if excel.exists():facts.extend(json.loads(excel.read_text(encoding='utf-8')))
    pdf=DATA/'extracted/pdf-facts.json'
    if pdf.exists():facts.extend(json.loads(pdf.read_text(encoding='utf-8')))
    all_sources={s['id']:s for s in [*sources,*generated]}
    support=DATA/'catalogue/reconciliation-sources.json'
    if support.is_file():
        for source in json.loads(support.read_text(encoding='utf-8')):
            all_sources.setdefault(source['id'],source)
    rawdb=DATA/'derived/plfss.new.sqlite'
    rawdb.unlink(missing_ok=True)
    db=sqlite3.connect(rawdb)
    db.execute('CREATE TABLE sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE facts (id INTEGER PRIMARY KEY, exercise INTEGER, stage TEXT, domain TEXT, perimeter TEXT, entity TEXT, metric TEXT, amount_cents INTEGER, edition INTEGER, priority INTEGER, source_id TEXT, payload TEXT NOT NULL)')
    for source in all_sources.values():db.execute('INSERT INTO sources VALUES (?,?)',(source['id'],json.dumps(source,ensure_ascii=False)))
    for f in facts:db.execute('INSERT INTO facts (exercise,stage,domain,perimeter,entity,metric,amount_cents,edition,priority,source_id,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)',tuple(f[k] for k in ('exercise','stage','domain','perimeter','entity','metric','amount_cents','edition','priority','source_id'))+(json.dumps(f,ensure_ascii=False),))
    db.execute('CREATE INDEX position ON facts(domain,perimeter,exercise,stage,metric,entity)')
    db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT)')
    version=hashlib.sha256(json.dumps(facts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    db.execute('INSERT INTO metadata VALUES (?,?)',('data_version',version))
    db.commit();db.close();rawdb.replace(DATA/'derived/plfss.sqlite')
    (DATA/'catalogue/normalized-sources.json').write_text(json.dumps(list(all_sources.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    (DATA/'derived/facts.json').write_text(json.dumps(facts,ensure_ascii=False),encoding='utf-8')
    (ROOT/'reports/table-inventory.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    result=dict(facts=len(facts),unique_positions=len({tuple(f[k] for k in ('exercise','stage','domain','perimeter','entity','metric')) for f in facts}),sources=len(all_sources),zero_observations=sum(f['amount_cents']==0 for f in facts),data_version=version,per_year=dict(Counter(str(f['exercise']) for f in facts)))
    (ROOT/'reports/normalized.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
