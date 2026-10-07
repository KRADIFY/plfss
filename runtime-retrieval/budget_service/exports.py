"""A dependency-free XLSX and reproducibility package from one computed selection."""
import csv,io,json,hashlib,zipfile
from xml.sax.saxutils import escape
from .model import STAGES
from .comparisons import COMPARISONS
from .evolution import LABELS


def fingerprint(data):
    value={k:data.get(k) for k in ('parameters','data_version','inflation','topic_version','calculation_version','action_detail_version')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def citation_urls(cell, urls):
    result=[]
    for source in cell.get('sources',[]):
        url=urls.get(source) or 'https://budget.lexmachine.net/api/download/'+source
        pages=sorted({r['page'] for r in cell.get('citations',[]) if r['source']==source})
        result.extend(url+'#page='+str(page) for page in pages) if pages else result.append(url)
    return ' '.join(result)


def source_locators(cell):
    locators=[f"{r['source']} · PDF p. {r['page']}" for r in cell.get('citations',[])]
    locators += [f"{r['source']} · {r['sheet']}!{r['column']}{r['row']}" for r in cell.get('spreadsheet_cells',[])]
    return '; '.join(locators)


def rows(data):
    p=data['parameters']
    yield ['Type','Budget','Périmètre','Code','Année','AE / CP','Étape','Montant EUR','Statut','Motif','Euros courants','Sources','Grain','Précision','Repères sources']
    for row in [dict(id=p['scope'],label=data['scope_label'],series=data['totals'],total=True)]+data['rows']:
        for annual in row['series']:
            for stage in STAGES:
                c=annual[stage]
                yield ['Total' if row.get('total') else 'Détail — ne pas additionner au total',p['budget'],row['label'],row['id'],annual['year'],p['measure'],STAGES[stage],c['value'],c['status'],c.get('reason',''),c.get('nominal'),', '.join(c.get('sources',[])),c.get('grain',''),c.get('precision') or ('Arrondi source' if c.get('approximate') else 'Précision source'),source_locators(c)]


def comparison_rows(data):
    yield ['Périmètre','Code','Année','Indicateur','Valeur','Unité','Statut','Explication','Sources']
    for row in [dict(id=data['parameters']['scope'],label=data['scope_label'],series=data['totals'])]+data['rows']:
        for annual in row['series']:
            for key,c in annual['comparisons'].items():
                yield [row['label'],row['id'],annual['year'],COMPARISONS[key],c['value'],c['unit'],c['status'],c['reason'],', '.join(c['sources'])]


def evolution_rows(data):
    yield ['Périmètre','Code','Année','AE / CP','Étape','Indicateur','Valeur %','Statut','Année de référence','Explication','Sources','Opérandes et indices']
    for row in [dict(id=data['parameters']['scope'],label=data['scope_label'],series=data['totals'])]+data['rows']:
        for annual in row['series']:
            for stage,metrics in annual.get('evolution',{}).items():
                for key,c in metrics.items():
                    yield [row['label'],row['id'],annual['year'],data['parameters']['measure'],STAGES[stage],LABELS[key],c['value'],c['status'],c['reference_year'],c['reason'],', '.join(c['sources']),json.dumps(c['operands'],ensure_ascii=False)]

def evolution_csv(annual,stage,first):
    metrics=annual.get('evolution',{}).get(stage,{})
    for key in LABELS:
        c=metrics.get(key,{})
        yield str(c['value']).replace('.',',') if c.get('value') is not None else ''
        yield c.get('status','unavailable')
    yield first
    yield ' '.join(sorted({s for c in metrics.values() for s in c['sources']}))
    yield ' | '.join(dict.fromkeys(c['reason'] for c in metrics.values() if c['status']!='ok'))

def xlsx(data,sources):
    selection=[['Paramètre','Valeur']]+[[k,json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)] for k,v in data['parameters'].items()]
    selection += [['Version des calculs',data.get('calculation_version','')],['Version des données',data['data_version']],['Empreinte de sélection',data['selection_id']],['Inflation',json.dumps(data['inflation'],ensure_ascii=False)],['Limites',' '.join(data['notes'])]]
    if data.get('action_detail_version'): selection.append(['Version du détail par action',data['action_detail_version']])
    sheets=[('Crédits',rows(data)),('Écarts et taux',comparison_rows(data)),('Sélection',selection),('Sources',[['Identifiant','Titre','URL','SHA-256','Chemin']]+[[r.get('id',''),r.get('title',''),r.get('url',''),r.get('sha256',''),r.get('path','')] for r in sources])]
    sheets.append(('Évolution annuelle',evolution_rows(data)))
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    out=io.BytesIO()
    def col(i):
        s=''
        while i:i,k=divmod(i-1,26);s=chr(65+k)+s
        return s
    def clean(v):return ''.join(c for c in str(v) if c in '\t\n\r' or ord(c)>=32)[:32767]
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(name,values) in enumerate(sheets,1):
            xml=[f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="20" width="22" customWidth="1"/></cols><sheetData>']
            n=0;last=1
            for n,row in enumerate(values,1):
                last=len(row);xml.append(f'<row r="{n}">')
                for j,value in enumerate(row,1):
                    if value is None:continue
                    ref=col(j)+str(n)
                    if isinstance(value,(int,float)) and not isinstance(value,bool):xml.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:xml.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(clean(value))}</t></is></c>')
                xml.append('</row>')
            xml.append(f'</sheetData><autoFilter ref="A1:{col(last)}{n}"/></worksheet>');z.writestr(f'xl/worksheets/sheet{i}.xml',''.join(xml))
    return out.getvalue()
