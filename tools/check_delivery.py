"""Check collected-file integrity and arithmetic independently of UI rendering."""
import hashlib
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plfss_service.store import Store
from tools.audit_source import check as reread


def main():
    data = ROOT / "data"
    sources = json.loads((data / "catalogue/normalized-sources.json").read_text(encoding="utf-8"))
    facts = json.loads((data / "derived/facts.json").read_text(encoding="utf-8"))
    integrity_errors, hashes = [], {}
    for source in sources:
        if source["status"] != "downloaded":
            continue
        target = (data / source["path"]).resolve()
        if not target.is_relative_to(data.resolve()) or not target.is_file():
            integrity_errors.append(dict(source_id=source["id"], reason="missing_file"))
            continue
        if str(target) not in hashes:
            hashes[str(target)] = hashlib.sha256(target.read_bytes()).hexdigest()
        digest = hashes[str(target)]
        if target.stat().st_size != source["bytes"] or digest != source["sha256"]:
            integrity_errors.append(dict(source_id=source["id"], reason="file_content_changed"))
    # Compare receipts - expenses - balance for the SAME source row and year.
    # A billion-euro rounded value denotes an interval, not exact cents.
    groups = defaultdict(dict)
    for f in facts:
        if f["domain"] == "EQUILIBRE":
            key = tuple(f.get(k) for k in ("source_id", "table_index", "exercise", "stage", "perimeter", "entity")) + (f.get('balance_row_index',f['row_index']),)
            groups[key][f["metric"]] = f
    arithmetic, arithmetic_errors, source_notices = 0, [], []
    by_source={s['id']:s for s in sources}
    reconciliation_path=data/'derived/source-reconciliations.json'
    reconciliations=json.loads(reconciliation_path.read_text(encoding='utf-8')).get('items',[]) if reconciliation_path.is_file() else []
    for key, group in groups.items():
        if not {"RECETTES", "DEPENSES", "SOLDE"}.issubset(group):
            continue
        arithmetic += 1
        r, d, s = (group[m] for m in ("RECETTES", "DEPENSES", "SOLDE"))
        gap = r["amount_cents"] - d["amount_cents"] - s["amount_cents"]
        rounding_cents = sum(Decimal(f["precision_eur"]) * 100 / 2 for f in (r, d, s))
        if abs(gap) > rounding_cents:
            # Do not excuse an extraction error by calling it a source issue:
            # reread all three original cells independently first.
            source_errors=[reread(f,by_source[f['source_id']],data) for f in (r,d,s)]
            if any(source_errors):
                arithmetic_errors.append(dict(source=key[0],year=key[2],perimeter=key[4],entity=key[5],gap_cents=gap,source_errors=source_errors))
                continue
            def bn(cents):return format(Decimal(cents)/Decimal(10**11),'f').replace('.',',')
            text=(f"Le tableau source publie {bn(r['amount_cents'])} Md€ de recettes, {bn(d['amount_cents'])} Md€ de dépenses et {bn(s['amount_cents'])} Md€ de solde. "
                  f"Recettes moins dépenses donne {bn(r['amount_cents']-d['amount_cents'])} Md€. L’écart dépasse les arrondis publiés. "
                  "Les trois cellules originales ont été relues ; leurs valeurs sont conservées sans correction automatique. Rapprochement des publications à finaliser.")
            source_notices.append(dict(key=list(key[:3]+key[4:]),stage=key[3],source_sha=r['source_sha'],
                source_id=key[0],table_index=key[1],exercise=key[2],perimeter=key[4],entity=key[5],balance_row_index=key[6],
                gap_cents=gap,published_rounding_cents=str(rounding_cents),values_cents={m:g['amount_cents'] for m,g in group.items()},
                status='source_cells_reread_reconciliation_pending',explanation=text,url=by_source[key[0]]['url']))
            notice=source_notices[-1]
            matched=[n for n in reconciliations if n['key']==notice['key'] and n['source_sha']==notice['source_sha'] and n['values_cents']==notice['values_cents']]
            if len(matched)==1:
                review=matched[0]
                # A notice cannot inherit a documentary analysis after an
                # amount or supporting file has changed.
                evidence=review.get('evidence',[])
                valid_evidence=bool(evidence) and all(e.get('status')=='downloaded' and (data/e['path']).is_file() and hashlib.sha256((data/e['path']).read_bytes()).hexdigest()==e['sha256'] for e in evidence)
                if valid_evidence:
                    notice.update(status='source_difference_documented_values_retained',documentary_category=review['category'],
                        resolved_value=False,explanation=text.replace('Rapprochement des publications à finaliser.','Rapprochement documentaire : '+review['explanation']),supporting_documents=evidence)
    notice_path=data/'derived/source-notices.json'
    notice_path.write_text(json.dumps(source_notices,ensure_ascii=False,indent=2),encoding='utf-8')
    store = Store(data)
    matrices, conflicts, selections = 0, [], 0
    for domain, perimeters, metrics in (("EQUILIBRE", ("ROBSS", "RG", "ROBSS_FSV", "RG_FSV", "FSV"), ("RECETTES", "DEPENSES", "SOLDE")), ("ONDAM", ("ROBSS",), ("DEPENSES",))):
        for perimeter in perimeters:
            for metric in metrics:
                for stages in (("PLFSS", "LFSS", "CONSTATE"), ("PLFSS_RECTIF", "LFSS_RECTIF"), ("PROJECTION",)):
                    matrix = store.matrix(domain, perimeter, 2017, 2027, metric, stages)
                    matrices += 1
                    for row in [matrix["total"], *matrix["rows"]]:
                        for col, cell in zip(matrix["columns"], row["cells"]):
                            if cell["status"] == "divergence":
                                conflicts.append(dict(domain=domain, perimeter=perimeter, metric=metric, entity=row["entity"], **col))
                    if matrix["rows"]:
                        excluded = (matrix["rows"][0]["entity"],)
                        filtered = store.matrix(domain, perimeter, 2017, 2027, metric, stages, excluded)
                        assert filtered["total"] == matrix["total"], "Published consolidated total changed"
                        for index, selected in enumerate(filtered["selection"]["cells"]):
                            values = [r["cells"][index]["amount_cents"] for r in filtered["rows"] if not r["excluded"] and r["cells"][index]["amount_cents"] is not None]
                            assert selected["amount_cents"] == (sum(values) if values else None), "Selection sum differs"
                        selections += 1
    used = {f["source_id"] for f in facts}
    failures = [{k: s.get(k) for k in ("id", "title", "url", "publication_year", "error")} for s in sources if s["status"] != "downloaded"]
    result = dict(data_version=store.meta()["data_version"], observations=len(facts),
                  checked_files=sum(s["status"] == "downloaded" for s in sources),
                  integrity_errors=integrity_errors, balance_checks=arithmetic,
                  arithmetic_errors=arithmetic_errors, matrix_scenarios=matrices,
                  source_arithmetic_notices=source_notices,source_balance_passed=not source_notices,
                  exclusion_checks=selections, source_divergences=conflicts,
                  collected_source_entries=len(sources), sources_with_qualified_values=len(used),
                  failed_downloads=failures, source_families=dict(Counter(s["family"] for s in sources)),
                  vectorized=Store(data).meta()['vectorized'], published=False,
                  documentary_global_validated=False,
                  passed=not integrity_errors and not arithmetic_errors and not conflicts,
                  scope="Fichiers collectés, cellules intégrées, équilibres par source et tableaux du service. Ne démontre pas l’exploitation de tous les tableaux des annexes.")
    (ROOT / "reports/delivery-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("observations", "checked_files", "balance_checks", "matrix_scenarios", "exclusion_checks", "passed")}))
    if not result["passed"]:
        print(json.dumps(dict(integrity_errors=integrity_errors, arithmetic_errors=arithmetic_errors, source_divergences=conflicts), ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
