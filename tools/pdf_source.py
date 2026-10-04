"""Qualify reviewed CCSS historical ONDAM columns, retaining the PDF cell locator.

The three grids were visually checked. No values are hardcoded: extraction is
repeated from the archived PDF, and fails if headers, rows or units change.
"""
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plfss_service.model import amount, norm

SPECS = (
    ("7bff7036aecda95e0661d859", 77, 2017, "2019-09"),
    ("0d22cca4fc65b258e99875a6", 75, 2018, "2020-09"),
    ("207f7d2c23ef1b43e7e35838", 74, 2019, "2021-09"),
)
DETAILS = (
    ("SOINS_VILLE", 0, "Soins de ville"),
    ("ETABLISSEMENTS_SANTE", 1, "Établissements de santé"),
    ("PERSONNES_AGEES", 3, "Contribution aux établissements et services pour personnes âgées"),
    ("PERSONNES_HANDICAPEES", 4, "Contribution aux établissements et services pour personnes handicapées"),
    ("FIR", 5, "Dépenses relatives au Fonds d’intervention régional"),
    ("AUTRES", 6, "Autres prises en charge"),
)


def extract(source, data, page_number, year, reference_date):
    path = Path(data) / source["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        raise ValueError("PDF source hash changed")
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_number - 1]
        body = page.extract_text() or ""
        if not re.search(r"Md\s*€|milliards?", body, re.I):
            raise ValueError("Billion-euro unit is not stated on the reviewed page")
        table = page.find_tables()[0]
        rows = table.extract()
        if len(rows) != 3 or norm(rows[0][1]) != "constat" + str(year):
            raise ValueError("Reviewed historical result column changed")
        # The PDF groups detail labels and numbers in one tall table row.
        labels = norm(rows[2][0])
        checks = ("soinsdeville", "etablissementsdesante", "medicosociaux",
                  "personnesagees", "personneshandicapees", "interventionregional", "autres")
        positions = [labels.find(label) for label in checks]
        if -1 in positions or positions != sorted(positions):
            raise ValueError("Reviewed detail labels changed")
        values = rows[2][1].splitlines()
        if len(values) != 7 or not all(re.fullmatch(r"-?\d+,\d", v.strip()) for v in values):
            raise ValueError("Reviewed detail values changed")
        title = re.search(r"Tableau\s*1[^\n]*Réalisations[^\n]*", body)
        context = (title[0] + ". " if title else "") + f"Constat historique {year}, unité milliards d’euros ; rapport CCSS {reference_date}. Le total est publié séparément des sous-objectifs arrondis."
        facts = []
        for entity, row_index, line, label, raw in (
            ("ONDAM", 1, None, "Total ONDAM publié", rows[1][1]),
            *((entity, 2, line, label, values[line]) for entity, line, label in DETAILS),
        ):
            bbox = table.rows[row_index].cells[1]
            facts.append(dict(exercise=year, edition=source["publication_year"],
                kind="CCSS_RESULTATS", stage="CONSTATE", domain="ONDAM", perimeter="ROBSS",
                entity=entity, metric="DEPENSES", amount_cents=amount(raw, 10**9),
                raw=raw, unit_eur=10**9, precision_eur="100000000", source_id=source["id"],
                source_sha=digest, page_number=page_number, table_index=0,
                row_index=row_index, column_index=1, line_index=line,
                pdf_bbox=[round(v, 3) for v in bbox], row_label=label,
                column_label=rows[0][1].replace("\n", " "), context=context,
                reference_date=reference_date, priority=100))
        return facts


def main():
    data = ROOT / "data"
    sources = {s["id"]: s for s in json.loads((data / "catalogue/documents.json").read_text(encoding="utf-8"))}
    facts = [f for sid, page, year, date in SPECS
             for f in extract(sources[sid], data, page, year, date)]
    target = data / "extracted/pdf-facts.json"
    target.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(qualified_pdf_observations=len(facts), years=[2017, 2018, 2019])))


if __name__ == "__main__":
    main()
