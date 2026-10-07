"""Adapters for legacy PLF layouts and the two annex budgets."""
import re
from decimal import Decimal
from .model import code, parts, budget_code, cents
from .normalize import read_table, dict_rows, get, column_key

def legacy_plf(importer, record, year):
    rows=read_table(record)
    budget=budget_code(rows[1][1])
    destination=budget=='BA'
    for line,row in enumerate(rows[4:],5):
        if len(row)<9 or not re.fullmatch(r'\d{3}',str(row[1]).strip()): continue
        p,a,s=parts(row[1],row[2],row[4] if destination else '')
        category='' if destination else code(row[3])
        dims=(budget,'',row[0],p,'',a,row[3] if destination else '',s,row[5] if destination else '',category,category[:1])
        for measure,column in [('AE',7 if destination else 6),('CP',9 if destination else 8)]:
            importer.add(record,line,year,'PLF',measure,dims,row[column],str(rows[3][column]))

def annex_budget(importer,record,year,measure):
    aviation=record['title'].startswith('BACEA')
    mission='Contrôle et exploitation aériens' if aviation else 'Publications officielles et information administrative'
    mission_code=importer.missions.get(column_key(mission),'')
    originals={column_key(h):h for h in read_table(record)[0]}
    for line,row in dict_rows(record):
        match=re.match(r'^(\d{3})\s*-\s*(.*)$',str(get(row,'Programme')).strip())
        title=re.match(r'^Titre\s+(\d)',str(get(row,'Libelle')))
        # Financial balancing operations and the FdC deduction are outside credit titles.
        if not match or not title: continue
        dims=('BA',mission_code,mission,match[1],match[2],'','','','','',title[1])
        mapping={
            'LFI':['AE_Initiales'] if measure=='AE' else ['CP_Initiaux','CP_Initiales'],
            'OUVERT':["Total_des_autorisations_d'engagement"] if measure=='AE' else ['Total_des_credits_de_paiement','Total_des_credits_de_paiements'],
            'EXEC':['Autorisations_consommees_nettes','Autorisations_consommees'] if measure=='AE' else ['Depenses_nettes'],
            'FONGIBILITE':['Fongibilite_asymetrique','Fongibilite_intertitres'],
            'PLRG_OUVERTURE':['Modif_Ouvertures'], 'PLRG_ANNULATION':['Modif_Annulations'],
            'REPORT_SORTANT':['Autorisations_reportees_a_N+1'] if measure=='AE' else ['Credits_reportes_a_N+1'],
        }
        for stage,fields in mapping.items():
            for field in fields:
                if column_key(field) in row:
                    importer.add(record,line,year,stage,measure,dims,get(row,field),str(originals[column_key(field)])); break
        for stage,kind in [('LEGIS','legislatives'),('REGLEMENT','reglementaires')]:
            keys=[k for k in row if kind in k and ('ouverture' in k or 'annulation' in k or 'modifications' in k)]
            values=[cents(row[k]) for k in keys]
            if keys and all(v is not None for v in values):
                importer.add(record,line,year,stage,measure,dims,Decimal(sum(values))/100,' + '.join(str(originals[k]) for k in keys))

def extend(importer):
    for r in importer.manifest:
        title=r.get('title','')
        if re.fullmatch(r'PLF2018-(BG|CS|CF)-Msn-Nat.csv',title) or title=='PLF2018-BA-Msn-Dest.csv': legacy_plf(importer,r,2018)
        elif title=='PLF2017-BA-Msn-Dest.csv': legacy_plf(importer,r,2017)
        elif re.fullmatch(r'(BACEA-Dev_(AEN|CPN)|BAPOIA-Synt_(AE|CP))-202[345].csv',title):
            annex_budget(importer,r,int(title[-8:-4]),'AE' if ('_AE' in title) else 'CP')
