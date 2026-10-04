"""Retry a PDF using compact repeated context, preserving complete metadata.

Only the optional repeated prefix is shortened. Every original context field,
table cell and positioned page remains in the encoded fields and raw proof.
No word split, truncation or artificial overlap is added.
"""
from pathlib import Path
import argparse,ast,json,shutil
import prepare_vectorization as prep


def compact_serializer(original):
    path=prep.OUT/'code/vectorisation_table_text_word_safe.py'
    tree=ast.parse(path.read_text('utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='serialize_table')
    replacements=0
    for node in ast.walk(function):
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix_budget' for t in node.targets):
            node.value=ast.Constant(value=0);replacements+=1
    if replacements!=1:raise ValueError('Frozen prefix assignment differs')
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    env=dict(original.__globals__)
    exec(compile(module,str(Path(__file__)), 'exec'),env)
    return env['serialize_table']


def main(source_id):
    settings=json.loads((prep.OUT/'preparation-contract.json').read_text('utf-8'))
    if prep.sha(Path(prep.__file__))!=settings['adapter_sha256']:raise ValueError('Frozen adapter changed')
    _,tables,_,_=prep.runtime(settings);original=tables.serialize_table
    compact=compact_serializer(original);events=[]
    def guarded(table,context,tokenizer,max_tokens=800):
        try:return original(table,context,tokenizer,max_tokens)
        except ValueError as exc:
            if str(exc) not in ('Indivisible source word exceeds the token budget; no truncation or in-word split',
                    'Serialized chunk exceeds its token contract'):raise
        for ceiling in range(max_tokens,max(63,max_tokens-32),-1):
            try:
                result=compact(table,context,tokenizer,max_tokens=ceiling)
                if not all(c['tokens']==len(tokenizer.encode(c['text']).ids)<=800 for c in result['chunks']):
                    raise ValueError('Compact prefix exceeds the final token budget')
                events.append(dict(page=context['page'],table_id=context['table_id'],successful_ceiling=ceiling,
                    source_text_conserved=result['contract']['source_text_conserved'],
                    source_characters=result['contract']['source_characters']))
                return result
            except ValueError as exc:
                if str(exc)!='Serialized chunk exceeds its token contract':raise
        raise ValueError('Compact context cannot fit; keep source held')
    tables.serialize_table=guarded
    items=json.loads((prep.OUT/'source-inventory.json').read_text('utf-8'))['items']
    item=next(i for i in items if i['source']['id']==source_id);sid=item['source']['sha256']
    receipt_path=prep.OUT/'documents'/(sid+'.receipt.json')
    if receipt_path.exists():
        old=json.loads(receipt_path.read_text('utf-8'))
        if old['preparation_identity']!=settings['preparation_identity'] or prep.sha(prep.OUT/old['path'])!=old['sha256']:
            raise ValueError('Existing source checkpoint changed')
        return old
    previous=prep.OUT/'documents'/(sid+'.jsonl.gz.partial')
    archive=prep.OUT/'pre-compact-context';archive.mkdir(exist_ok=True)
    if previous.exists() and not (archive/previous.name).exists():shutil.copyfile(previous,archive/previous.name)
    result=prep.stage_one(item,settings)
    code_sha=prep.sha(Path(__file__));code=prep.OUT/'code'/('compact_context_guard-'+code_sha[:16]+'.py')
    if not code.exists():shutil.copyfile(Path(__file__),code)
    result['compact_context_guard']=dict(code_sha256=code_sha,path=code.relative_to(prep.OUT).as_posix(),
        events=events,source_fields_changed=False,optional_prefix_budget=0,original_serializer_sha256=settings['code']['vectorisation_table_text_word_safe.py'])
    prep.save(receipt_path,result)
    prep.save(prep.ROOT/'reports'/('compact-context-pdf-'+source_id+'.json'),result['compact_context_guard'])
    print(prep.dump(dict(source_id=source_id,completed=True,chunks=result['chunks'],events=events)),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-id',required=True)
    main(parser.parse_args().source_id)
