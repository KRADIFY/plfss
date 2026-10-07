"""Transactional, idempotent import of reviewed national PAP 2026 amounts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


FIELDS = "year stage measure budget mission mission_label program program_label action action_label subaction subaction_label category title cents source line field approximate".split()
KEY_FIELDS = "year stage measure budget mission program".split()
STAGES = {"PLF", "FDC_PREVU"}
MEASURES = {"AE", "CP"}


def rows_digest(db: sqlite3.Connection, limit: int) -> str:
    digest = hashlib.sha256()
    for item in db.execute("SELECT * FROM facts WHERE rowid<=? ORDER BY rowid", (limit,)):
        digest.update(json.dumps(tuple(item), ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def row_key(item: dict) -> tuple:
    return tuple(item[key] for key in KEY_FIELDS)


def row_value(item: dict) -> tuple:
    return tuple(item[key] for key in FIELDS)


def validate_plan(plan: dict) -> None:
    rows = plan["rows"]
    additions = plan["additions"]
    existing = plan["existing_rows_preserved"]
    sources = plan["sources"]
    checks = plan["checks"]
    total_checks = plan["mission_total_checks"]
    summary = plan["summary"]

    if plan.get("version") != "pap-2026-national-1":
        raise ValueError("Unexpected national PAP plan version")
    if len(sources) != 32 or len({item["mission"] for item in sources}) != 32:
        raise ValueError("Expected one source for each of the 32 budget-general missions")
    source_by_mission = {item["mission"]: item for item in sources}
    if len({item["source_id"] for item in sources}) != len(sources):
        raise ValueError("Duplicate PAP source")
    for source in sources:
        if len(source["source_sha256"]) != 64 or not source["url"].lower().endswith(".pdf"):
            raise ValueError("Invalid PAP source metadata")

    keys = [row_key(item) for item in rows]
    if len(rows) != 372 or len(keys) != len(set(keys)):
        raise ValueError("Duplicate or unexpected national PAP rows")
    for item in rows:
        if (
            item["year"] != 2026
            or item["stage"] not in STAGES
            or item["measure"] not in MEASURES
            or item["budget"] != "BG"
            or item["action"]
            or item["subaction"]
            or not item["program"]
            or not isinstance(item["cents"], int)
            or item["cents"] <= 0
            or item["line"] != item["page"]
        ):
            raise ValueError("Invalid reviewed national PAP observation")
        source = source_by_mission.get(item["mission"])
        if not source or item["source"] != source["source_id"]:
            raise ValueError("Observation/source mission mismatch")
    if any(item["mission"] == "TA" and item["program"] == "362" for item in rows):
        raise ValueError("Blank Ecology programme 362 must not be imported")

    row_values = {row_value(item) for item in rows}
    addition_values = {row_value(item) for item in additions}
    existing_values = {row_value(item) for item in existing}
    if addition_values & existing_values or addition_values | existing_values != row_values:
        raise ValueError("Plan additions and preserved rows do not partition the reviewed rows")
    if len(additions) != 338 or len(existing) != 34:
        raise ValueError("Unexpected national PAP partition")

    if len(checks) != 128 or not all(item.get("passed") for item in checks):
        raise ValueError("Unchecked PAP programme")
    if len(total_checks) != 110 or not all(item.get("passed") for item in total_checks):
        raise ValueError("Unchecked PAP mission total")
    published = {
        (item["mission"], item["stage"], item["measure"]): item["cents"]
        for item in total_checks
    }
    calculated = {}
    for item in rows:
        key = (item["mission"], item["stage"], item["measure"])
        calculated[key] = calculated.get(key, 0) + item["cents"]
    if calculated != published:
        raise ValueError("Programme sums differ from published PAP mission totals")

    expected_summary = {
        "documents": len(sources),
        "programmes_checked": len(checks),
        "rows_total": len(rows),
        "rows_already_present": len(existing),
        "rows_to_add": len(additions),
        "mission_totals_checked": len(total_checks),
        "database_mutated": False,
    }
    if summary != expected_summary:
        raise ValueError("PAP plan summary differs from its contents")


def install(data: Path = Path("/data")) -> None:
    plan_path = Path(__file__).parent / "data" / "pap-2026-national.json"
    plan = json.loads(plan_path.read_text(encoding="utf8"))
    validate_plan(plan)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    target = data / "derived" / "budget.sqlite"
    db = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    source_metadata = {}
    source_hashes = {}
    newly_imported_sources = 0
    for source in plan["sources"]:
        stored = db.execute("SELECT data FROM sources WHERE id=?", (source["source_id"],)).fetchone()
        if not stored:
            raise ValueError("PAP source missing from application catalogue: " + source["source_id"])
        metadata = json.loads(stored["data"])
        path = data / metadata["path"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if metadata.get("sha256") != source["source_sha256"] or digest != source["source_sha256"]:
            raise ValueError("PAP source hash mismatch: " + source["mission"])
        source_metadata[source["source_id"]] = metadata
        source_hashes[source["mission"]] = digest
        if not metadata.get("imported"):
            newly_imported_sources += 1

    planned = sorted(
        (row_value(item) for item in plan["rows"]),
        key=lambda item: tuple(item[FIELDS.index(key)] for key in KEY_FIELDS),
    )
    planned_by_key = {
        tuple(item[FIELDS.index(key)] for key in KEY_FIELDS): item
        for item in planned
    }
    existing_by_key = {}
    for key, expected in planned_by_key.items():
        found = db.execute(
            "SELECT " + ",".join(FIELDS) + " FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=? AND program=? AND action='' AND subaction=''",
            key,
        ).fetchall()
        if len(found) > 1:
            raise ValueError("Duplicate existing PAP fact: " + "/".join(map(str, key)))
        if found:
            actual = tuple(found[0][field] for field in FIELDS)
            if actual != expected:
                raise ValueError("Existing PAP fact conflicts with reviewed plan: " + "/".join(map(str, key)))
            existing_by_key[key] = actual
    to_insert = [item for key, item in planned_by_key.items() if key not in existing_by_key]

    total_rows = {
        (item["mission"], item["stage"], item["measure"]): item
        for item in plan["mission_total_checks"]
    }
    for (mission, stage, measure), item in total_rows.items():
        found = db.execute(
            "SELECT cents FROM reconciled_totals WHERE year=2026 AND stage=? AND measure=? AND budget='BG' AND path=?",
            (stage, measure, mission),
        ).fetchone()
        if found and found[0] != item["cents"]:
            raise ValueError(f"Existing reconciled total conflicts: {mission}/{stage}/{measure}")

    meta = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM meta")}
    if not to_insert and meta.get("pap2026_national", {}).get("plan_sha256") == plan_sha:
        print(json.dumps({"state": "already_installed", "facts": len(planned)}, ensure_ascii=False))
        db.close()
        return

    count = db.execute("SELECT count(*) FROM facts").fetchone()[0]
    last = db.execute("SELECT max(rowid) FROM facts").fetchone()[0]
    before = rows_digest(db, last)
    backup = data / "imports" / "pap-2026-national-20260920"
    backup.mkdir(parents=True, exist_ok=True)
    backup_file = backup / "budget-before.sqlite"
    if not backup_file.exists():
        with sqlite3.connect(backup_file) as destination:
            db.backup(destination)

    staged = data / "derived" / "budget.pap2026-national-staged.sqlite"
    if staged.exists():
        raise ValueError("National PAP staging database exists; inspect it before resuming")
    new = sqlite3.connect(staged)
    new.execute("PRAGMA temp_store=MEMORY")
    db.backup(new)
    if to_insert:
        new.executemany(
            "INSERT INTO facts(" + ",".join(FIELDS) + ") VALUES(" + ",".join("?" for _ in FIELDS) + ")",
            to_insert,
        )
    source_by_mission = {item["mission"]: item["source_id"] for item in plan["sources"]}
    for (mission, stage, measure), item in total_rows.items():
        found = new.execute(
            "SELECT cents FROM reconciled_totals WHERE year=2026 AND stage=? AND measure=? AND budget='BG' AND path=?",
            (stage, measure, mission),
        ).fetchone()
        if not found:
            new.execute(
                "INSERT INTO reconciled_totals VALUES(?,?,?,?,?,?,?)",
                (2026, stage, measure, "BG", mission, item["cents"], source_by_mission[mission]),
            )
    for source_id, metadata in source_metadata.items():
        metadata["imported"] = True
        new.execute("UPDATE sources SET data=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), source_id))

    now = datetime.now(timezone.utc).isoformat()
    updates = {
        "fact_count": count + len(to_insert),
        "built_at": now,
        "data_version": hashlib.sha256((meta["data_version"] + plan_sha).encode()).hexdigest(),
        "imported_source_count": meta["imported_source_count"] + newly_imported_sources,
        "stats": dict(new.execute("SELECT year||'/'||stage||'/'||budget,count(*) FROM facts GROUP BY year,stage,budget")),
        "pap2026_national": {
            "plan_sha256": plan_sha,
            "sources": source_hashes,
            "missions": len(plan["sources"]),
            "programmes_checked": len(plan["checks"]),
            "mission_totals_checked": len(plan["mission_total_checks"]),
            "observations": len(planned),
            "observations_added": len(to_insert),
            "limits": plan["limits"],
        },
    }
    for key, value in updates.items():
        new.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
    if rows_digest(new, last) != before:
        raise ValueError("Original facts changed during national PAP import")
    new.commit()
    if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Invalid staged national PAP database")
    new.close()
    db.close()
    staged.chmod(0o644)

    old_audit = data / "derived" / "data-audit.json"
    audit = None
    if old_audit.exists():
        shutil.copyfile(old_audit, backup / "data-audit-before.json")
        audit = json.loads(old_audit.read_text(encoding="utf8"))
    staged.replace(target)
    if audit and audit.get("success") and audit.get("built_at") == meta["built_at"]:
        audit.update(
            built_at=now,
            checked_at=now,
            fact_count=updates["fact_count"],
            pap2026_national_checks={
                "source_sha256": source_hashes,
                "missions": len(plan["sources"]),
                "programmes": len(plan["checks"]),
                "mission_totals": len(plan["mission_total_checks"]),
                "original_facts_preserved": count,
                "original_facts_sha256": before,
            },
        )
        old_audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf8")
        old_audit.chmod(0o644)

    receipt = {
        "installed_at": now,
        "facts_added": len(to_insert),
        "previous_fact_count": count,
        "current_fact_count": updates["fact_count"],
        "sources_checked": len(source_hashes),
        "programme_checks": len(plan["checks"]),
        "mission_total_checks": len(plan["mission_total_checks"]),
        "original_facts_sha256": before,
        "plan_sha256": plan_sha,
    }
    (backup / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8")
    shutil.copyfile(plan_path, backup / "plan.json")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    install()