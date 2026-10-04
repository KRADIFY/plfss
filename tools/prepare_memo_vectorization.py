"""Apply the supplied Nos Deniers memo by route, preserving old checkpoints.

Only local preparation. PDF table pages reuse the corrected positioned reading;
other records use the archived main Chunker, never a universal overlap switch.
"""
from pathlib import Path
import argparse,collections,gzip,json,os,sqlite3,sys,time
import prepare_vectorization as previous
import prepare_historical_excel as excel

ROOT=previous.ROOT
BASE=previous.OUT
OUT=BASE/'memo-20261004'
PROFILE='nos-deniers-memo-20261001-routes-historiques'
save=previous.save
sha=previous.sha
dump=previous.dump
digest=previous.digest


def freeze():
    choice=json.loads((BASE/'historical-protocol-choice.json').read_text('utf-8'))
    if choice.get('profile')!=PROFILE or choice.get('decision_required'):
        raise ValueError('The supplied memo profile has not been selected')
    reference=Path(choice['reference_document_path'])
    if sha(reference)!=choice['reference_document_sha256']:
        raise ValueError('Memo changed: preserve this preparation and qualify the new document')
    old=json.loads((BASE/'preparation-contract.json').read_text('utf-8'))
    if sha(ROOT/'tools/prepare_vectorization.py')!=old['adapter_sha256']:
        raise ValueError('The archived source-preparation adapter changed')
    hist,config,code=excel.freeze()
    contract={k:old[k] for k in ('model','revision','tokenizer_sha256','dense_dimensions','dense_dtype',
        'dense_normalized','sparse_dtype','colbert','max_tokens','truncate','context_included_in_token_limit',
        'part_size','allow_automatic_numeric_fact')}
    contract.update(profile=PROFILE,memo_sha256=choice['reference_document_sha256'],
        previous_preparation_identity=old['preparation_identity'],historical_excel_identity=hist['identity'],
        historical_code=hist['code'],table_code=old['code'],adapter_sha256=sha(Path(__file__)),
        artificial_overlap='by_route',generic_overlap_max_tokens=150,pdf_table_artificial_overlap=0,
        pdf_selection='tables_or_grid_candidate_not_resolved_or_manual_ocr',
        generic_context_max_tokens=100,rows_per_batch=32,source_blank_states_retained=True,
        source_blank_fields_repeated_in_generic_encoder_text=False,range_compaction_enabled=False,
        source_and_old_checkpoints_preserved=True,gpu_launched=False,paid_compute_authorized=False)
    contract['preparation_identity']=digest(dump(contract))
    path=OUT/'preparation-contract.json'
    if path.is_file() and json.loads(path.read_text('utf-8'))['preparation_identity']!=contract['preparation_identity']:
        raise ValueError('Keep the existing memo preparation: its code or contract differs')
    OUT.mkdir(exist_ok=True);save(path,contract)
    env,chunker,_=excel.runtime(config,code)
    return contract,hist,config,code,env,chunker


def context_for(item,env,section=''):
    refs=[dict(years=[r['publication_year']],stage_documentaire=r['family']) for r in item['references']]
    context=env['context_for'](refs).replace('Nos Deniers.','PLFSS.',1)
    return context+('. Section : '+section if section else '')


def selected_pdf(rec):
    return bool(rec.get('tables')) or 'grid_candidate_not_resolved' in rec.get('issues',[]) or rec.get('method','').startswith('ocr')


def memo_document(item,contract,hist,config,code,env,chunker):
    sid=item['source']['sha256'];directory=OUT/'documents';directory.mkdir(exist_ok=True)
    output=directory/(sid+'.jsonl.gz');receipt_path=directory/(sid+'.receipt.json')
    if receipt_path.is_file():
        receipt=json.loads(receipt_path.read_text('utf-8'))
        if receipt['preparation_identity']!=contract['preparation_identity'] or sha(output)!=receipt['sha256']:
            raise ValueError('Memo checkpoint changed')
        return receipt
    if item['format']=='xlsx':
        inherited=excel.prepare(item,hist,config,code)
        input_path=BASE/inherited['path'];schema='historical_excel'
    else:
        parent_path=BASE/'documents'/(sid+'.receipt.json')
        if not parent_path.is_file():raise FileNotFoundError('Source extraction is not complete')
        inherited=json.loads(parent_path.read_text('utf-8'))
        if inherited['preparation_identity']!=contract['previous_preparation_identity']:
            raise ValueError('Source extraction belongs to a different contract')
        input_path=BASE/inherited['path'];schema='positioned_records'
    if sha(input_path)!=inherited['sha256'] or sha(ROOT/'data'/item['source']['path'])!=sid:
        raise ValueError('Source or staged extraction changed')
    counts=collections.Counter();routes=collections.Counter();start=time.time()
    pending=[];blocks=[];locators=[];section='';temp=output.with_name(output.name+'.partial')
    with gzip.open(input_path,'rt',encoding='utf-8') as reader,gzip.open(temp,'wt',encoding='utf-8',compresslevel=3) as writer:
        def emit(record,chunks,route,quality=None):
            no=counts['records']+1
            record=dict(record,record_number=no,source_sha256=sid)
            ref=digest(sid+'\n'+record['locator']+'\n'+dump(record))
            qualities=dict(source_kind='source_'+item['format'],numeric_status='raw_not_validated_facts',
                allow_automatic_numeric_fact=False,null_is_not_zero=True,header_status='source_candidates_not_certified')
            qualities.update(quality or {})
            result=[]
            for index,ch in enumerate(chunks,1):
                c=dict(ch,record_ref=ref,locator=ch.get('locator') or record['locator']+f'/part:{index}',
                    quality=qualities|ch.get('quality',{}),preparation_route=route)
                if not 0<c['tokens']==chunker.count(c['text'])<=800:
                    raise ValueError('Final passage violates the 800-token contract')
                if c['quality']['allow_automatic_numeric_fact'] is not False:
                    raise ValueError('A passage may not certify a financial amount')
                result.append(c)
            writer.write(dump(dict(record_ref=ref,record=record,chunks=result,quality=qualities,route=route))+'\n')
            counts['records']+=1;counts['chunks']+=len(result);counts['tokens']+=sum(c['tokens'] for c in result)
            routes[route]+=1

        def flush():
            if not pending:return
            context=context_for(item,env,section)
            chunks=[dict(text=text,body=body,tokens=chunker.count(text)) for text,body in chunker.chunks(context,blocks)] if blocks else []
            record=dict(kind='historical_batch',source_records=list(pending),serialized_blocks=list(blocks),
                source_locators=list(locators),locator='|'.join(locators),section=section,context=context,
                normalization='NFC_remove_NUL_trim_edges',blank_fields_retained_in_source_records=True)
            emit(record,chunks,'generic_conditional_150')
            pending.clear();blocks.clear();locators.clear()

        headers={}
        for line in reader:
            obj=json.loads(line)
            if schema=='historical_excel':
                if 'structure' in obj:
                    rec=obj['structure'];counts['source_records']+=1
                    emit(dict(rec,locator=rec.get('locator','structure:'+str(counts['source_records']))),[],
                        'generic_conditional_150');continue
                counts['source_records']+=len(obj['records'])
                emit(dict(kind='historical_batch',source_records=obj['records'],serialized_blocks=obj['serialized_blocks'],
                    source_locators=obj['source_locators'],locator='|'.join(obj['source_locators']),section=obj['section'],
                    context=obj['context'],normalization='NFC_remove_NUL_trim_edges',blank_fields_retained_in_source_records=True),
                    obj['chunks'],'generic_conditional_150');continue
            rec=obj['record'];counts['source_records']+=1
            if rec['kind']=='page':
                flush();counts['pages']+=1
                if selected_pdf(rec):
                    if bool(rec.get('tables')) or 'grid_candidate_not_resolved' in rec.get('issues',[]):
                        if not rec.get('review',{}).get('review_required'):
                            raise ValueError('A table page lacks its corrected double reading')
                    emit(rec,obj['chunks'],'pdf_corrected_zero',obj.get('quality'))
                    counts['specialized_pdf_pages']+=1
                else:
                    section=rec.get('section','');context=context_for(item,env,section)
                    raw=[b['text'] for b in rec.get('blocks',[])]
                    parts=[dict(text=text,body=body,tokens=chunker.count(text),page=rec['page'],
                        page_label=rec.get('page_label'),paragraph_number_kind='extractor_block_order_not_official_number')
                        for text,body in chunker.chunks(context,raw)]
                    # The complete positioned record is retained, even where
                    # the legacy Chunker normalizes its text for encoding.
                    emit(dict(rec,legacy_body_blocks=raw,context=context),parts,'generic_conditional_150')
                    counts['generic_pdf_pages']+=1
            elif rec['kind']=='table':
                sheet=rec.get('sheet','')
                if pending and sheet!=section:flush()
                section=sheet
                candidates=headers.setdefault(sheet,[]) if 'row_start' in rec else []
                if len(candidates)<5:candidates.extend(rec['rows'][:5-len(candidates)])
                width=max((len(row) for row in candidates),default=0)
                labels=['contexte non certifie: '+' / '.join(env['clean'](row[col])[:120]
                    for row in candidates if col<len(row) and row[col] is not None) for col in range(width)]
                row_lines=list(env['table_lines'](rec,labels))
                pending.append(rec);blocks.extend(row_lines);locators.append(rec['locator']+'/table:1')
                if 'row_start' not in rec or len(blocks)>=32:flush()
            elif rec['kind']=='text':
                flush();section=rec.get('section','')
                pending.append(rec);blocks.append(rec['text']);locators.append(rec['locator']);flush()
            else:
                flush();emit(rec,[],'generic_conditional_150')
        flush()
    os.replace(temp,output)
    receipt=dict(source_sha256=sid,source_id=item['source']['id'],path=output.relative_to(OUT).as_posix(),
        sha256=sha(output),preparation_identity=contract['preparation_identity'],parent_path=str(input_path),
        parent_sha256=inherited['sha256'],routes=dict(routes),**counts,elapsed_seconds=round(time.time()-start,2),
        source_changed=False,gpu_launched=False,paid_compute_authorized=False)
    save(receipt_path,receipt);return receipt


def export(contract,items,receipts):
    # Reuse the existing export writer with a task-local output directory.
    # Its fixed schema preserves every record_ref and every citation occurrence.
    old_out=previous.OUT
    try:
        previous.OUT=OUT
        result=previous.export(contract,items,receipts,[])
    finally:previous.OUT=old_out
    return result


def main(limit=0):
    contract,hist,config,code,env,chunker=freeze()
    inventory=json.loads((BASE/'source-inventory.json').read_text('utf-8'))
    items=inventory['items']
    seen={}
    for item in items:
        unique={}
        for ref in item['references']:
            if ref['id'] in unique and unique[ref['id']]['sha256']!=ref['sha256']:
                raise ValueError('A reference ID points to incompatible sources')
            unique[ref['id']]=ref
            if ref['id'] in seen and seen[ref['id']]!=ref['sha256']:
                raise ValueError('A reference ID points to incompatible documents')
            seen[ref['id']]=ref['sha256']
        item['references']=list(unique.values())
    save(OUT/'source-inventory.json',dict(inventory,items=items))
    selected=items[:limit] if limit else items
    done=[];held=[];start=time.time()
    (OUT/'prepare.pid').write_text(str(os.getpid())+'\n','ascii')
    for item in selected:
        try:done.append(memo_document(item,contract,hist,config,code,env,chunker))
        except Exception as exc:
            held.append(dict(source_id=item['source']['id'],source_sha256=item['source']['sha256'],
                error=str(exc)[:350],type=type(exc).__name__))
        state=dict(profile=PROFILE,state='preparing_memo_routes',done=len(done),expected=len(items),held=len(held),
            decision_required=False,alignment_required=True,complete=False,passages=sum(r['chunks'] for r in done),
            tokens=sum(r['tokens'] for r in done),elapsed_seconds=round(time.time()-start,1),
            gpu_launched=False,paid_compute_authorized=False,original_checkpoints_preserved=True)
        save(OUT/'status.json',state)
        if (len(done)+len(held))%25==0:print(dump(state),flush=True)
    save(OUT/'receipts.json',done);save(OUT/'held-documents.json',held)
    if not limit and not held and len(done)==len(items):
        state.update(export(contract,items,done),state='ready_for_independent_validation')
    else:state['state']='partial_memo_preparation' if not limit else 'memo_pilot'
    save(OUT/'status.json',state)
    save(ROOT/'reports/current-preparation-state.json',state)
    print(dump(state),flush=True)
    return state


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=0)
    main(parser.parse_args().limit)
