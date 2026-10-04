"""Audit the memo preparation: conservation with permitted legacy overlap.

Uses source proofs, exact token counts, immutable parent hashes and independent
coverage checks. A partial pilot cannot authorize an encoder input.
"""
from pathlib import Path
import argparse,collections,gzip,json,sqlite3,sys,unicodedata
import prepare_memo_vectorization as prep
import verify_vectorization as positioned
ROOT=prep.ROOT;BASE=prep.BASE;OUT=prep.OUT
sha=prep.sha;save=prep.save;digest=prep.digest


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC',str(text)).replace('\x00','').split())


def check_generic_coverage(blocks,chunks,token_count=None):
    source=' '.join(normalized(b) for b in blocks if normalized(b))
    # Repeated identical rows can have several valid locations. Keep possible
    # contiguous alignments rather than greedily choosing the first match.
    states={(0,0):0}
    for ch in chunks:
        body=normalized(ch['body'])
        if not body:raise ValueError('Empty legacy body')
        next_states={}
        for (start,end),overlaps in states.items():
            pos=source.find(body,start)
            while pos>=0 and pos<=end+1:
                new_end=pos+len(body)
                gap=source[end:pos] if pos>end else ''
                if new_end>end and (not gap or gap.isspace()):
                    if pos>=end or token_count is None or token_count(source[pos:end])<=150:
                        key=(pos,new_end);value=overlaps+int(pos<end)
                        next_states[key]=min(next_states.get(key,value),value)
                pos=source.find(body,pos+1)
        if not next_states:raise ValueError('A legacy body differs from its normalized source')
        states=next_states
    endings=[v for (_,end),v in states.items() if end==len(source)]
    if not endings:raise ValueError('The legacy bodies do not cover all source content')
    return min(endings)


def verify_record(obj,tokenizer):
    rec=obj['record'];chunks=obj['chunks'];route=obj['route']
    ref=digest(rec['source_sha256']+'\n'+rec['locator']+'\n'+prep.dump(rec))
    if obj['record_ref']!=ref:raise ValueError('Evidence record hash differs')
    for ch in chunks:
        if ch['record_ref']!=ref or ch['preparation_route']!=route:
            raise ValueError('Broken route or evidence reference')
        count=len(tokenizer.encode(ch['text']).ids)
        if not 0<count==ch['tokens']<=800:raise ValueError('Final token count or ceiling differs')
        if ch['quality']['allow_automatic_numeric_fact'] is not False:
            raise ValueError('Unsupported numeric certification')
    if route=='pdf_corrected_zero':
        return 0,positioned.verify_record(obj,tokenizer)
    if route!='generic_conditional_150':raise ValueError('Unknown memo route')
    if rec['kind']=='page':
        expected=[b.get('text','') for b in rec.get('blocks',[])]
        if rec['legacy_body_blocks']!=expected:raise ValueError('Positioned PDF blocks changed')
        if any(ch.get('page')!=rec['page'] for ch in chunks):raise ValueError('Wrong PDF physical page')
        return check_generic_coverage(expected,chunks,lambda text:len(tokenizer.encode(text).ids)),[]
    if rec['kind']=='historical_batch':
        # Independently check that every nonempty source cell or text block is
        # represented. NULL and empty strings are retained in source_records.
        blocks=rec['serialized_blocks'];serialized='\n'.join(blocks)
        source_lines={}
        for block in blocks:
            if block.startswith('Ligne ') and '. ' in block:
                key=block.split('. ',1)[0]
                source_lines.setdefault(key,[]).append(block)
        for record in rec['source_records']:
            if record['kind']=='text':
                if normalized(record['text']) not in normalized(serialized):raise ValueError('Text block missing')
            elif record['kind']=='table':
                for row_no,row in enumerate(record['rows'],record.get('row_start',1)):
                    populated=False
                    for col,value in enumerate(row,1):
                        if value is None or value=='':continue
                        populated=True
                        text=prep.dump(value) if isinstance(value,(dict,list)) else str(value)
                        lines=source_lines.get('Ligne '+str(row_no),[])
                        cell_pattern='Colonne '+str(col)
                        found=False
                        for line in lines:
                            cell_start=line.find(cell_pattern)
                            if cell_start<0:continue
                            after=line[cell_start+len(cell_pattern):]
                            if not after.startswith((' [',' :')):continue
                            if after.startswith(' ['):
                                value_start=after.find('] : ')
                                if value_start<0:continue
                                value_and_tail=after[value_start+4:]
                            else:value_and_tail=after[3:]
                            if value_and_tail==text or value_and_tail.startswith(text+' | Colonne '):
                                found=True;break
                        if not found:
                            raise ValueError('Populated table cell or column missing')
                    if populated and ('Ligne '+str(row_no)+'.') not in serialized:
                        raise ValueError('Table row reference missing')
        return check_generic_coverage(blocks,chunks,lambda text:len(tokenizer.encode(text).ids)),[]
    if chunks:raise ValueError('Unknown source kind has encoded content')
    return 0,[]


def main(available=False):
    from tokenizers import Tokenizer
    config=json.loads((OUT/'preparation-contract.json').read_text('utf-8'))
    if config['adapter_sha256']!=sha(ROOT/'tools/prepare_memo_vectorization.py'):
        raise ValueError('Memo adapter changed')
    if sha(BASE/'assets/tokenizer.json')!=config['tokenizer_sha256']:raise ValueError('Tokenizer changed')
    for name,value in config['historical_code'].items():
        if sha(BASE/'historical-main-code'/name)!=value:raise ValueError('Historical code changed')
    for name,value in config['table_code'].items():
        if sha(BASE/'code'/name)!=value:raise ValueError('Table preparation code changed')
    tk=Tokenizer.from_file(str(BASE/'assets/tokenizer.json'));tk.no_truncation();tk.no_padding()
    items=json.loads((OUT/'source-inventory.json').read_text('utf-8'))['items']
    bysha={i['source']['sha256']:i for i in items};results=[];errors=[];critical=[]
    reviews_path=BASE/'page-reviews.json'
    reviews=json.loads(reviews_path.read_text('utf-8')) if reviews_path.is_file() else []
    review_hash=sha(reviews_path) if reviews_path.is_file() else ''
    audit_dir=OUT/'audit';audit_dir.mkdir(exist_ok=True)
    for file in sorted((OUT/'documents').glob('*.receipt.json')):
        receipt=json.loads(file.read_text('utf-8'));sid=receipt['source_sha256'];item=bysha[sid]
        try:
            if receipt['preparation_identity']!=config['preparation_identity']:
                raise ValueError('Document profile differs')
            path=OUT/receipt['path'];actual=sha(path);source_hash=sha(ROOT/'data'/item['source']['path'])
            parent=sha(Path(receipt['parent_path']))
            if actual!=receipt['sha256'] or source_hash!=sid or parent!=receipt['parent_sha256']:
                raise ValueError('Source or prepared evidence hash differs')
            guard=receipt.get('boundary_guard',{})
            if guard:
                if guard['code_sha256']!=sha(ROOT/'tools/guard_memo_boundaries.py'):
                    raise ValueError('Word-boundary guard code changed')
                if guard['original_sha256']!=sha(Path(guard['original_path'])):
                    raise ValueError('Original pre-guard checkpoint changed')
                if guard['source_proofs_changed'] is not False or guard['inherited_overlap_max_tokens']!=150:
                    raise ValueError('Guard changed source proof or inherited overlap')
            identity=digest(config['preparation_identity']+sha(Path(__file__))+actual+source_hash+parent+review_hash+prep.dump(guard))
            cached=audit_dir/(sid+'.json')
            if cached.exists() and json.loads(cached.read_text('utf-8'))['audit_identity']==identity:
                result=json.loads(cached.read_text('utf-8'));results.append(result);critical+=result['critical_pages'];continue
            counts=collections.Counter();pages=[]
            def parent_records():
                with gzip.open(receipt['parent_path'],'rt',encoding='utf-8') as parent_stream:
                    for parent_line in parent_stream:
                        parent_obj=json.loads(parent_line)
                        if 'record' in parent_obj:yield parent_obj['record']
                        elif 'structure' in parent_obj:yield parent_obj['structure']
                        else:yield from parent_obj['records']
            parent_iterator=iter(parent_records())
            with gzip.open(path,'rt',encoding='utf-8') as stream:
                for line in stream:
                    obj=json.loads(line)
                    if obj['record']['record_number']!=counts['records']+1:raise ValueError('Source record order differs')
                    raw_records=obj['record'].get('source_records',[obj['record']])
                    for raw in raw_records:
                        original=next(parent_iterator,None)
                        if original is None or any(key not in raw or raw[key]!=value for key,value in original.items()):
                            raise ValueError('A source field, formula, blank state or positioned record changed')
                    overlaps,issues=verify_record(obj,tk)
                    for issue in issues:
                        approved=[r for r in reviews if r['source_sha256']==sid and r['page']==issue['page']
                            and r['status']=='visually_verified_blank_graphic_page']
                        if len(approved)==1:
                            proof=ROOT/approved[0]['rendered_path']
                            if proof.is_file() and sha(proof)==approved[0]['rendered_sha256']:continue
                        pages.append(dict(issue,source_sha256=sid,source_id=item['source']['id']))
                    counts['records']+=1;counts['chunks']+=len(obj['chunks'])
                    counts['tokens']+=sum(c['tokens'] for c in obj['chunks']);counts['overlap_boundaries']+=overlaps
            if next(parent_iterator,None) is not None:raise ValueError('Source records missing from selected preparation')
            if any(counts[k]!=receipt[k] for k in ('records','chunks','tokens')):
                raise ValueError('Document receipt counts differ')
            result=dict(source_sha256=sid,audit_identity=identity,passed=True,critical_pages=pages,**counts)
            save(cached,result);results.append(result);critical+=pages
        except Exception as exc:errors.append(dict(source_sha256=sid,error=str(exc),type=type(exc).__name__))
        if (len(results)+len(errors))%50==0:print(prep.dump(dict(documents_verified=len(results),errors=len(errors))),flush=True)
    summary=dict(profile=config['profile'],documents_verified=len(results),documents_expected=len(items),
        passages_checked=sum(r['chunks'] for r in results),tokens_checked=sum(r['tokens'] for r in results),
        overlap_boundaries=sum(r.get('overlap_boundaries',0) for r in results),errors=errors,critical_pages=critical,
        all_documents_checked=len(results)==len(items),input_checked=False,gpu_launched=False,paid_compute_authorized=False)
    if not available:
        status=json.loads((OUT/'export-status.json').read_text('utf-8'))
        if not status['complete'] or status['documents_prepared']!=len(items):raise ValueError('Export is not closed')
        if sha(OUT/'gpu_input/public.bge-m3.jsonl')!=status['input_sha256']:raise ValueError('Encoder input changed')
        if sha(OUT/'catalogue.sqlite')!=status['catalogue_sha256']:raise ValueError('Evidence catalogue changed')
        with sqlite3.connect((OUT/'catalogue.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Catalogue integrity error')
            rows=db.execute('SELECT id,text,tokens FROM passages ORDER BY id');n=t=0
            with (OUT/'gpu_input/public.bge-m3.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    obj=json.loads(line);row=next(rows,None)
                    if row is None or row!=tuple(obj[k] for k in ('id','text','tokens')):
                        raise ValueError('Encoder input differs from proof catalogue')
                    if obj['id']!=digest('public\n'+obj['text']) or obj['tokens']!=len(tk.encode(obj['text']).ids):
                        raise ValueError('Input identifier or tokens differ')
                    n+=1;t+=obj['tokens']
            if next(rows,None) is not None or n!=status['passages'] or t!=status['tokens']:
                raise ValueError('Input coverage differs')
            if db.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0]!=sum(r['chunks'] for r in results):
                raise ValueError('Citation coverage differs')
            expected={(r['id'],i['source']['sha256']) for i in items for r in i['references']}
            if set(db.execute('SELECT id,asset_sha FROM sources'))!=expected:raise ValueError('Source coverage differs')
        summary.update(input_checked=True,input_sha256=status['input_sha256'])
    summary['passed']=not errors and not critical and summary['all_documents_checked'] and summary['input_checked']
    save(OUT/('preparation-audit.partial.json' if available else 'preparation-audit.json'),summary)
    print(prep.dump(summary),flush=True);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--available',action='store_true');a=p.parse_args();result=main(a.available)
    if result['errors'] or result['critical_pages'] or (not a.available and not result['passed']):raise SystemExit(1)
