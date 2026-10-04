"""Repair only proven in-word legacy splits in the new PLFSS preparation.

Original source proofs, archived adapters and checkpoints remain untouched.
The inherited packing and conditional 150-token overlap are unchanged.
"""
from pathlib import Path
import argparse,collections,gzip,json,os,re,shutil
import prepare_memo_vectorization as prep
import verify_memo_vectorization as audit


def word_safe_class(base,clean):
    class WordSafeChunker(base):
        def atoms(self,text,budget):
            text=clean(text)
            if not text:return
            if self.count(text)<=budget:
                yield text;return
            sentences=re.split(r'\n\s*\n|(?<=[.!?;])\s+',text)
            if len(sentences)>1:
                for sentence in sentences:yield from self.atoms(sentence,budget)
                return
            # Split an overlong paragraph only at whitespace, never within a
            # word or number. Recount after choosing the natural boundary.
            start=0
            while start<len(text):
                while start<len(text) and text[start].isspace():start+=1
                remaining=text[start:]
                if not remaining:return
                if self.count(remaining)<=budget:
                    yield remaining;return
                encoded=self.tk.encode(remaining,add_special_tokens=False)
                candidate=encoded.offsets[min(budget-8,len(encoded.ids))-1][1]
                boundaries=[m.start() for m in re.finditer(r'\s+',remaining)]
                eligible=[n for n in boundaries if n<=candidate]
                end=eligible[-1] if eligible else (boundaries[0] if boundaries else len(remaining))
                while end>0 and self.count(remaining[:end])>budget:
                    eligible=[n for n in boundaries if n<end]
                    if not eligible:break
                    end=eligible[-1]
                if end<=0 or self.count(remaining[:end])>budget:
                    raise ValueError('Indivisible source word exceeds the token budget; no truncation or in-word split')
                yield remaining[:end]
                start+=end
    return WordSafeChunker


def repair_source(sid,contract,chunker):
    root=prep.OUT;path=root/'documents'/(sid+'.jsonl.gz')
    receipt_path=path.with_name(sid+'.receipt.json')
    receipt=json.loads(receipt_path.read_text('utf-8'))
    if receipt['preparation_identity']!=contract['preparation_identity'] or prep.sha(path)!=receipt['sha256']:
        raise ValueError('Memo receipt or checkpoint differs')
    temporary=path.with_name(path.name+'.word-guard.partial')
    changed=[];counts=collections.Counter()
    try:
        with gzip.open(path,'rt',encoding='utf-8') as reader,gzip.open(temporary,'wt',encoding='utf-8',compresslevel=3) as writer:
            for line in reader:
                obj=json.loads(line);rec=obj['record']
                if obj['route']=='generic_conditional_150' and rec['kind'] in ('page','historical_batch'):
                    blocks=rec['legacy_body_blocks'] if rec['kind']=='page' else rec['serialized_blocks']
                    try:audit.check_generic_coverage(blocks,obj['chunks'],chunker.count)
                    except ValueError:
                        metadata=dict(obj['chunks'][0]) if obj['chunks'] else {}
                        chunks=[]
                        for index,(text,body) in enumerate(chunker.chunks(rec['context'],blocks),1):
                            c=dict(metadata,text=text,body=body,tokens=chunker.count(text),record_ref=obj['record_ref'],
                                locator=rec['locator']+f'/part:{index}',quality=obj['quality'],preparation_route=obj['route'])
                            if not 0<c['tokens']<=800:raise ValueError('Word guard exceeds the final token budget')
                            chunks.append(c)
                        audit.check_generic_coverage(blocks,chunks,chunker.count)
                        changed.append(dict(record_number=rec['record_number'],before=len(obj['chunks']),after=len(chunks)))
                        obj['chunks']=chunks
                audit.verify_record(obj,chunker.tk)
                counts['records']+=1;counts['chunks']+=len(obj['chunks'])
                counts['tokens']+=sum(c['tokens'] for c in obj['chunks'])
                writer.write(prep.dump(obj)+'\n')
        if not changed:return dict(source_sha256=sid,changed=False)
        archive=root/'pre-guard';archive.mkdir(exist_ok=True)
        original=archive/path.name;original_receipt=archive/receipt_path.name
        if original.exists():
            if prep.sha(original)!=receipt.get('boundary_guard',{}).get('original_sha256'):
                raise ValueError('Previous guard archive differs')
        else:
            shutil.copyfile(path,original);shutil.copyfile(receipt_path,original_receipt)
        guard=dict(code_sha256=prep.sha(Path(__file__)),original_path=str(original),original_sha256=prep.sha(original),
            reason='Independent conservation audit detected an in-word legacy split',
            inherited_overlap_max_tokens=150,source_proofs_changed=False,records=changed)
        os.replace(temporary,path)
        receipt.update(counts,sha256=prep.sha(path),boundary_guard=guard)
        prep.save(receipt_path,receipt)
        return dict(source_sha256=sid,changed=True,records=len(changed),chunks=counts['chunks'])
    finally:
        if temporary.exists():temporary.unlink()


def main():
    contract,hist,config,code,env,legacy=prep.freeze()
    chunker=word_safe_class(type(legacy),env['clean'])(config)
    summary=json.loads((prep.OUT/'preparation-audit.partial.json').read_text('utf-8'))
    targets=[e['source_sha256'] for e in summary['errors']
        if e['error']=='A legacy body differs from its normalized source']
    results=[];held=[]
    for sid in targets:
        try:results.append(repair_source(sid,contract,chunker))
        except Exception as exc:held.append(dict(source_sha256=sid,error=str(exc),type=type(exc).__name__))
    result=dict(results=results,held=held,gpu_launched=False,source_proofs_changed=False)
    prep.save(prep.OUT/'boundary-guard-results.json',result)
    print(prep.dump(result),flush=True)
    return result


if __name__=='__main__':
    result=main()
    if result['held']:raise SystemExit(1)
