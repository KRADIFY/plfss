"""Retry observed Cour links via an existing SSH client; no remote file is written.

The public PDF/ZIP bytes are downloaded locally. No application or configuration
on either VPS is modified, and the runtime PLFSS service has no SSH dependency.
"""
import concurrent.futures
import hashlib
import json
import shlex
import subprocess
from urllib.parse import urlsplit

import collect


def ssh_fetch(url, path):
    if not collect.allowed(url) or urlsplit(url).hostname != "www.ccomptes.fr":
        raise ValueError("Only catalogued Cour files can use this retrieval route")
    marker = "\nPLFSS_PUBLIC_SOURCE_META_20261003_"
    remote = " ".join(shlex.quote(v) for v in (
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--connect-timeout", "8", "--max-time", "50",
        "--write-out", marker + "%{http_code}|%{url_effective}|%{content_type}", url))
    response = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                               "marie@109.199.112.132", remote], capture_output=True, timeout=70)
    if response.returncode:
        raise RuntimeError("Official file retrieval via SSH failed, exit=" + str(response.returncode))
    content, metadata = response.stdout.rsplit(marker.encode(), 1)
    status, final_url, mime = metadata.decode().strip().split("|", 2)
    if status != "200" or not collect.allowed(final_url) or not content:
        raise ValueError("Invalid public source response")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(content)
    temporary.replace(path)
    return dict(final_url=final_url, mime=mime.split(";")[0], bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest())


def main():
    catalogue = collect.DATA / "catalogue/documents.json"
    records = {d["id"]: d for d in json.loads(catalogue.read_text(encoding="utf-8"))}
    pending = [d for d in records.values() if d["status"] != "downloaded" and urlsplit(d["url"]).hostname == "www.ccomptes.fr"]
    collect.fetch = ssh_fetch
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(collect.document_worker, pending):
            children = result.pop("children", [])
            records[result["id"]] = result
            for child in children:
                records[child["id"]] = child
            collect.atomic(catalogue, list(records.values()))
            results.append(dict(id=result["id"], status=result["status"], error=result.get("error")))
            print(json.dumps(dict(retried=len(results), expected=len(pending), recovered=sum(r["status"]=="downloaded" for r in results))), flush=True)
    previous = json.loads((collect.ROOT / "reports/collection.json").read_text(encoding="utf-8"))
    previous.update(checked_at=collect.now(), documents=len(records),
                    downloaded=sum(r["status"]=="downloaded" for r in records.values()),
                    failed=sum(r["status"]!="downloaded" for r in records.values()),
                    bytes=sum(r.get("bytes", 0) for r in records.values()))
    collect.atomic(collect.ROOT / "reports/collection.json", previous)
    collect.atomic(collect.ROOT / "reports/cour-retry.json", dict(results=results, route="Public source retrieval through existing SSH client; no remote file or service changed"))
    print(json.dumps(previous), flush=True)


if __name__ == "__main__":
    main()
