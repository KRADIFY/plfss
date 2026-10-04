"""Locate historical ONDAM tables in collected CCSS PDFs, without changing facts."""
import json, sys
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
docs = json.loads((ROOT / "data/catalogue/documents.json").read_text(encoding="utf-8"))
out = ROOT / "reports/ondam-pdf-inspection"
out.mkdir(exist_ok=True)
for source in docs:
    if "/CCSS/" not in source["url"] or source["publication_year"] not in (2018, 2019, 2020):
        continue
    reader = PdfReader(ROOT / "data" / source["path"])
    matches = []
    for index, page in enumerate(reader.pages):
        body = page.extract_text() or ""
        if "soins de ville" in body.lower() and "ondam" in body.lower() and ("constat" in body.lower() or "exécution" in body.lower()):
            target = out / f"{source['id']}-page-{index+1}.txt"
            target.write_text(body, encoding="utf-8")
            matches.append(dict(page=index+1, text=target.name))
    print(json.dumps(dict(source_id=source["id"], title=source["title"], matches=matches), ensure_ascii=False), flush=True)
