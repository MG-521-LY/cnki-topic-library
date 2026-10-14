#!/usr/bin/env python3
"""Offline state, screening, ranking and download verification for CNKI agents."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


STATES = {"pending", "in_progress", "downloaded", "failed", "no_access", "no_pdf", "waiting_user"}
METADATA = {"title", "authors", "year", "source", "doc_type", "field", "url", "doi", "cnki_id",
            "abstract", "keywords", "citations", "downloads", "fulltext_note"}
SCREEN_FIELDS = {"title", "authors", "year", "source", "doc_type", "field", "abstract", "keywords", "fulltext_note"}
SECRET_KEYS = re.compile(r"cookie|password|authorization|credential|session|token|signature|api.?key|secret", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False, newline="\n") as f:
            name = f.name
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


@contextmanager
def task_lock(root):
    """OS lock is released on process exit; no persistent stale PID locks."""
    lock = (root / ".task.lock").open("a+b")
    acquired = False
    try:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise ValueError("Task is busy. Wait for the other writer to finish.") from exc
        yield
    finally:
        if acquired:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def norm(value):
    return "".join(c for c in unicodedata.normalize("NFKC", str(value)).casefold() if c.isalnum())


def finite_number(value, label, low=0, high=float("inf")):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} outside allowed range")
    return number


def metric(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).replace(",", "").strip()
        if text in {"--", "—", "-", "未知", "暂无"}:
            return None
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(万|千|[kK])?\s*(次)?", text)
        if not m:
            raise ValueError("Unrecognized citation/download count; use null when unknown")
        return finite_number(m[1], "metric") * {None: 1, "万": 10000, "千": 1000, "k": 1000, "K": 1000}[m[2]]
    return finite_number(value, "metric")


def clean_url(value):
    if not value:
        return ""
    parts = urlsplit(str(value))
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Paper URL must be http/https without credentials")
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not SECRET_KEYS.search(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))


def scrub(value):
    if isinstance(value, dict):
        return {str(k): scrub(v) for k, v in value.items() if not SECRET_KEYS.search(str(k))}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return clean_url(value)
    return value


def clean_paper(raw):
    if not isinstance(raw, dict):
        raise ValueError("Each paper must be an object")
    if not isinstance(raw.get("title"), str) or not raw["title"].strip():
        raise ValueError("Each paper needs an observed title")
    p = {}
    for key in METADATA:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key in {"citations", "downloads"}:
            p[key] = metric(value)
        elif key == "year":
            if isinstance(value, bool) or not re.fullmatch(r"\d{4}", str(value)):
                raise ValueError("year must be a four-digit integer or null")
            p[key] = int(finite_number(value, "year", 1000, 2999))
        elif key == "keywords":
            if isinstance(value, str):
                value = [x.strip() for x in re.split(r"[;；,，]", value) if x.strip()]
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError("keywords must be strings")
            p[key] = value
        elif key == "authors" and isinstance(value, list):
            if any(not isinstance(v, str) for v in value):
                raise ValueError("authors must be strings")
            p[key] = "; ".join(value)
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        else:
            p[key] = value.strip()
    p["url"] = clean_url(p.get("url", ""))
    if p.get("doi"):
        p["doi"] = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", p["doi"], flags=re.I).strip().lower()
    if p.get("cnki_id"):
        p["cnki_id"] = p["cnki_id"].split(":")[-1].upper()
    elif p["url"]:
        qs = {k.casefold(): v for k, v in parse_qsl(urlsplit(p["url"]).query)}
        if qs.get("filename"):
            p["cnki_id"] = qs["filename"].upper()
    query = raw.get("query", "")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    p["queries"] = [query] if query else []
    return p


def same_paper(a, b):
    for key in ("doi", "cnki_id"):
        if a.get(key) and b.get(key):
            return a[key] == b[key]
    if a.get("url") and a["url"] == b.get("url"):
        return True
    if norm(a["title"]) != norm(b["title"]):
        return False
    if not a.get("authors") or not b.get("authors") or norm(a["authors"]) != norm(b["authors"]):
        return False
    return not (a.get("year") and b.get("year") and a["year"] != b["year"])


def eligible(p, data):
    return p.get("decision") == "include" and p.get("relevance", 0) >= data["min_relevance"]


def verify_file(path, allow_caj=False):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Download file is missing or is not a regular file")
    size = path.stat().st_size
    if size < 512:
        raise ValueError("File is too small to count as full text")
    with path.open("rb") as f:
        head = f.read(1024)
        f.seek(max(0, size - 4096))
        tail = f.read()
        if head.startswith(b"%PDF-"):
            if b"%%EOF" not in tail:
                raise ValueError("PDF is incomplete: missing end marker")
            fmt = "pdf"
        elif allow_caj and head.startswith((b"CAJ", b"CDS", b"KDH", b"TEB", b"HN")):
            fmt = "caj"
        else:
            raise ValueError("Not a supported full-text file (HTML/login pages are rejected)")
        f.seek(0)
        hasher = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
        digest = hasher.hexdigest()
    return {"file": str(path), "format": fmt, "bytes": size, "sha256": digest,
            "verified_at": now(), "verification": "signature-size-eof-sha256; not a structural PDF parse"}


def reconcile(data):
    seen = set()
    for p in data["papers"]:
        if p.get("status") != "downloaded":
            continue
        try:
            info = verify_file(p.get("file", ""), data["allow_caj"])
            if info["sha256"] != p.get("sha256"):
                raise ValueError("File content changed after verification")
            if info["sha256"] in seen:
                raise ValueError("Duplicate file content; cannot count as another paper")
            seen.add(info["sha256"])
        except (ValueError, OSError) as exc:
            p.update(status="failed", error=str(exc), updated_at=now())


def ranked(data):
    return sorted((p for p in data["papers"] if eligible(p, data)),
                  key=lambda p: (-p.get("score", 0), -p.get("relevance", 0), p["id"]))


def statistics(data):
    successful = [p for p in data["papers"] if eligible(p, data) and p["status"] == "downloaded"]
    active = [p for p in data["papers"] if eligible(p, data) and p["status"] == "in_progress"]
    waiting = [p["id"] for p in data["papers"] if p["status"] == "waiting_user"]
    return {"topic": data["topic"], "target": data["target"], "verified_downloaded": len(successful),
            "remaining": max(0, data["target"] - len(successful)), "complete": len(successful) >= data["target"],
            "candidates": len(data["papers"]), "eligible": len(ranked(data)),
            "unreviewed": sum(not p.get("decision") for p in data["papers"]),
            "excluded": sum(p.get("decision") == "exclude" for p in data["papers"]),
            "formats": dict(Counter(p["format"] for p in successful)),
            "states": dict(Counter(p["status"] for p in data["papers"])),
            "interrupted": [p["id"] for p in active], "waiting_user": waiting,
            "download_paused": bool(waiting)}


def cohort(p):
    year = p.get("year")
    return (p.get("field", "unknown"), p.get("doc_type", "unknown"), (year // 5) * 5 if year else "unknown")


def score_all(data):
    for p in data["papers"]:
        members = [m for m in data["papers"] if cohort(m) == cohort(p)]
        details = {}
        for key in ("citations", "downloads"):
            values = [m[key] for m in members if m.get(key) is not None]
            current = p.get(key)
            percentile = 0.5
            if current is not None and len(values) >= 5:
                percentile = (sum(v < current for v in values) + (sum(v == current for v in values) - 1) / 2) / (len(values) - 1)
            details[key] = {"percentile": round(percentile, 6), "missing": current is None,
                            "sample_size": len(values), "neutral": current is None or len(values) < 5}
        heat = sum(v["percentile"] for v in details.values()) / 2
        p.update(heat=round(heat, 6), heat_evidence=details,
                 score=round(0.8 * p.get("relevance", 0) + 20 * heat, 4))


def find(data, paper_id):
    for p in data["papers"]:
        if p["id"] == paper_id:
            return p
    raise ValueError("Unknown paper id")


def ingest(data, payload):
    rows = payload.get("papers") if isinstance(payload, dict) else payload
    logs = payload.get("search_log", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not isinstance(logs, list):
        raise ValueError("Expected papers array and optional search_log array")
    prepared = [clean_paper(r) for r in rows]
    added = merged = 0
    output = []
    for incoming in prepared:
        matches = [p for p in data["papers"] if same_paper(p, incoming)]
        if len(matches) == 1:
            p = matches[0]
            changed = False
            for key in METADATA:
                value = incoming.get(key)
                if value is None or value == "" or value == []:
                    continue
                if key in SCREEN_FIELDS and p.get(key) != value:
                    changed = True
                p[key] = value
            p["queries"] = list(dict.fromkeys(p["queries"] + incoming["queries"]))
            if changed:
                p["previous_review"] = {k: p[k] for k in ("decision", "relevance", "evidence", "reason") if k in p}
                for k in ("decision", "relevance", "evidence", "reason"):
                    p.pop(k, None)
            merged += 1
        else:
            seed = json.dumps(incoming, sort_keys=True, ensure_ascii=False) + ":" + str(len(data["papers"]))
            p = dict(incoming, id=hashlib.sha256(seed.encode()).hexdigest()[:16], status="pending", created_at=now())
            data["papers"].append(p)
            added += 1
        p["updated_at"] = now()
        output.append({"id": p["id"], "title": p["title"], "review_required": not bool(p.get("decision"))})
    data["search_log"].extend(scrub(logs))
    score_all(data)
    return {"added": added, "merged": merged, "papers": output}


def review(data, payload):
    if not isinstance(payload, list):
        raise ValueError("Review input must be an array")
    seen = set()
    for r in payload:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            raise ValueError("Each review needs an id")
        p = find(data, r["id"])
        if p["id"] in seen:
            raise ValueError("Duplicate id in review batch")
        seen.add(p["id"])
        if r.get("decision") not in {"include", "exclude"} or r.get("evidence") not in {"title", "abstract", "fulltext"}:
            raise ValueError("Invalid decision/evidence")
        reason = r.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Review needs a concrete reason")
        value = finite_number(r.get("relevance"), "relevance", 0, 100)
        if r["evidence"] == "abstract" and not p.get("abstract"):
            raise ValueError("Cannot claim abstract evidence when no abstract was collected")
        if r["evidence"] == "fulltext" and not p.get("fulltext_note"):
            if not p.get("file"):
                raise ValueError("Full-text evidence requires a reading note or verified local file")
            verify_file(p["file"], data["allow_caj"])
        p.update(decision=r["decision"], evidence=r["evidence"], reason=reason.strip(),
                 relevance=min(value, 70) if r["evidence"] == "title" else value, reviewed_at=now())
    score_all(data)
    return {"reviewed": len(payload), "eligible": len(ranked(data))}


def record(data, args):
    p = find(data, args.id)
    if args.status in {"in_progress", "downloaded"}:
        if not eligible(p, data):
            raise ValueError("Screen this candidate before downloading")
        if statistics(data)["download_paused"]:
            raise ValueError("Queue paused for user verification; reset waiting_user items after resolution")
    if args.status == "in_progress":
        if p["status"] != "pending":
            raise ValueError("Only a pending item can start; resolve interrupted/failed items explicitly")
        s = statistics(data)
        if s["remaining"] <= len(s["interrupted"]):
            raise ValueError("Target already reached or all remaining slots are active")
        p["attempts"] = p.get("attempts", 0) + 1
    if args.status == "downloaded":
        if not args.file:
            raise ValueError("Downloaded status requires --file")
        info = verify_file(args.file, data["allow_caj"])
        for other in data["papers"]:
            if other["id"] != p["id"] and other.get("sha256") == info["sha256"] and other["status"] == "downloaded":
                raise ValueError("Duplicate content already recorded for another paper")
        s = statistics(data)
        if p["status"] != "downloaded" and s["remaining"] <= 0:
            raise ValueError("Target already reached")
        p.update(info)
    if args.status in {"failed", "no_access", "no_pdf", "waiting_user"} and not args.reason:
        raise ValueError("Failure/waiting status requires --reason")
    p.update(status=args.status, error=args.reason or "", updated_at=now())
    return {"id": p["id"], "status": p["status"], "verified_downloaded": statistics(data)["verified_downloaded"]}


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    s = str(value)
    return "'" + s if s.lstrip().startswith(("=", "+", "-", "@")) or s.startswith(("\t", "\r", "\n")) else s


def export(data, root):
    import io
    fields = ["id", "title", "authors", "year", "source", "doc_type", "field", "doi", "url", "citations",
              "downloads", "decision", "relevance", "evidence", "reason", "heat", "score", "status", "error",
              "file", "format", "bytes", "sha256", "queries"]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    ordered = sorted(data["papers"], key=lambda p: (-p.get("score", 0), p["id"]))
    for p in ordered:
        writer.writerow([cell(p.get(k)) for k in fields])
    atomic_text(root / "library.csv", "\ufeff" + output.getvalue())
    s = statistics(data)
    write_json(root / "manifest.json", {"summary": s, "search_log": data["search_log"], "papers": ordered})
    def md(text):
        return str(text).replace("\n", " ").replace("\r", " ").replace("|", "\\|").replace("<", "&lt;")
    lines = ["# 知网文献任务报告", "", f"研究需求：{md(data['topic'])}", "",
             f"实际核验成功：**{s['verified_downloaded']} / {s['target']}**；缺口：{s['remaining']}。", "",
             f"候选：{s['candidates']}；符合筛选：{s['eligible']}；未评审：{s['unreviewed']}。", "",
             "## 检索与筛选范围", "", "本报告是实际检索样本内的优选，不能解释为全知网最热门文献。",
             "综合分80%相关性、20%热度；热度是同学科、文献类型、五年年份段内的指标分位数，缺失或样本不足时中性处理。",
             "PDF核验为签名、大小、结束标记与哈希初筛，未承诺完整结构解析。", ""]
    lines += ["```json", json.dumps(data["search_log"], ensure_ascii=False, indent=2), "```", "",
              "## 文献及处理结果", "", "| 标题 | 相关性 | 依据 | 热度数据 | 状态 | 入选/排除理由或失败原因 |", "|---|---:|---|---|---|---|"]
    for p in ordered:
        metrics = f"被引:{p.get('citations', '未知')} / 下载:{p.get('downloads', '未知')}"
        reason = p.get("error") or p.get("reason") or "尚未评审"
        if p["status"] == "downloaded" and not eligible(p, data):
            reason += "；不符合当前筛选，不计目标成功数"
        lines.append("| " + " | ".join(md(v) for v in (p["title"], p.get("relevance", ""), p.get("evidence", ""), metrics, p["status"], reason)) + " |")
    atomic_text(root / "report.md", "\n".join(lines) + "\n")
    return {"summary": s, "files": [str(root / x) for x in ("library.csv", "report.md", "manifest.json")]}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("init", "set-target", "ingest", "review", "rank", "next", "record", "status", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("--task", required=True, type=Path)
        if name == "init":
            sub.add_argument("--topic", required=True)
            sub.add_argument("--count", type=int, default=100)
            sub.add_argument("--min-relevance", type=float, default=65)
            sub.add_argument("--allow-caj", action="store_true")
        if name == "set-target":
            sub.add_argument("--count", type=int, required=True)
        if name in {"ingest", "review"}:
            sub.add_argument("--input", required=True, type=Path)
        if name == "next":
            sub.add_argument("--limit", type=int, default=1)
        if name == "record":
            sub.add_argument("--id", required=True)
            sub.add_argument("--status", required=True, choices=sorted(STATES))
            sub.add_argument("--file", type=Path)
            sub.add_argument("--reason")
    return p


def run(args):
    root = args.task.resolve()
    if args.command == "init":
        if not args.topic.strip() or not 1 <= args.count <= 10000:
            raise ValueError("A topic and a target between 1 and 10000 are required")
        finite_number(args.min_relevance, "min_relevance", 0, 100)
        root.mkdir(parents=True, exist_ok=True)
    elif not root.is_dir():
        raise ValueError("Task directory does not exist; initialize first")
    with task_lock(root):
        state_file = root / "task.json"
        if args.command == "init":
            if state_file.exists():
                raise ValueError("Task already exists; refusing to overwrite it")
            data = {"version": 1, "topic": args.topic.strip(), "target": args.count,
                    "min_relevance": args.min_relevance, "allow_caj": args.allow_caj,
                    "created_at": now(), "papers": [], "search_log": []}
            result = {"task": str(root), "target": args.count, "status": "initialized"}
        else:
            data = read_json(state_file)
            if data.get("version") != 1:
                raise ValueError("Unsupported task format")
            reconcile(data)
            if args.command == "set-target":
                if not 1 <= args.count <= 10000:
                    raise ValueError("Target must be an integer between 1 and 10000")
                previous = data["target"]
                data["target"] = args.count
                data.setdefault("target_history", []).append({"previous": previous, "target": args.count, "changed_at": now()})
                result = {"previous_target": previous, "summary": statistics(data)}
            elif args.command == "ingest":
                result = ingest(data, read_json(args.input))
            elif args.command == "review":
                result = review(data, read_json(args.input))
            elif args.command == "record":
                result = record(data, args)
            elif args.command == "rank":
                score_all(data)
                result = {"eligible": len(ranked(data)), "top": [{k: x.get(k) for k in ("id", "title", "score", "relevance")} for x in ranked(data)[:10]]}
            elif args.command == "next":
                if not 1 <= args.limit <= 100:
                    raise ValueError("limit must be between 1 and 100")
                s = statistics(data)
                limit = max(0, min(args.limit, s["remaining"] - len(s["interrupted"])))
                queue = [] if s["download_paused"] else [x for x in ranked(data) if x["status"] == "pending"][:limit]
                result = {"summary": s, "papers": queue}
            elif args.command == "export":
                result = export(data, root)
            else:
                result = statistics(data)
        data["updated_at"] = now()
        write_json(state_file, data)
        return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
