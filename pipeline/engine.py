from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = ["manifest", "pages", "units", "kps", "citations", "questions", "export"]
SOURCE_BUCKETS = ["slides", "textbook", "notes", "questions", "kp_seed"]


@dataclass
class RunResult:
    success: bool
    stage: str
    output_files: list[str]
    stats: dict[str, int]
    message: str = ""


class PipelineError(Exception):
    pass


def run_stage(course_id: str, stage: str, config_path: str | None = None, root_dir: str = ".") -> RunResult:
    if stage not in STAGES:
        raise PipelineError(f"Unsupported stage '{stage}'. Expected one of: {STAGES}")

    root = Path(root_dir)
    out_dir = root / "out" / course_id
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = out_dir / "pipeline.yaml.snapshot"
    if config_path:
        snapshot_path.write_text(Path(config_path).read_text(encoding="utf-8"), encoding="utf-8")

    dispatcher = {
        "manifest": _stage_manifest,
        "pages": _stage_pages,
        "units": _stage_units,
        "kps": _stage_kps,
        "citations": _stage_citations,
        "questions": _stage_questions,
        "export": _stage_export,
    }

    if stage == "export":
        for pre in ["manifest", "pages", "units", "kps", "citations", "questions"]:
            dispatcher[pre](course_id=course_id, root=root)

    result = dispatcher[stage](course_id=course_id, root=root)
    _write_pipeline_state(course_id, stage, result.stats, root)
    return result


def _course_source_dir(root: Path, course_id: str) -> Path:
    return root / "data" / course_id / "sources"


def _course_out_dir(root: Path, course_id: str) -> Path:
    return root / "out" / course_id


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _slugify(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return clean.lower() or "file"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_manifest(course_id: str, root: Path) -> RunResult:
    source_dir = _course_source_dir(root, course_id)
    out_dir = _course_out_dir(root, course_id)
    manifest: dict[str, Any] = {
        "course_id": course_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resources": [],
    }

    for bucket in SOURCE_BUCKETS:
        bucket_dir = source_dir / bucket
        if not bucket_dir.exists():
            continue
        for file_path in sorted(p for p in bucket_dir.iterdir() if p.is_file()):
            stem_slug = _slugify(file_path.stem)
            manifest["resources"].append(
                {
                    "resource_id": f"{course_id}__{bucket}__{stem_slug}",
                    "resource_type": bucket,
                    "file_name": file_path.name,
                    "relative_path": str(file_path.relative_to(root)),
                    "size": file_path.stat().st_size,
                    "sha1": _sha1(file_path),
                }
            )

    manifest_path = out_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return RunResult(True, "manifest", [str(manifest_path)], {"resources": len(manifest["resources"])})


def _extract_pages(file_path: Path) -> list[str]:
    if file_path.suffix.lower() in {".md", ".txt"}:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        pages = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return pages or [""]

    text = file_path.read_text(encoding="utf-8", errors="ignore") if file_path.suffix.lower() in {".json", ".csv"} else ""
    return [text or f"[UNPARSED_BINARY] {file_path.name}"]


def _stage_pages(course_id: str, root: Path) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    manifest = _load_json(out_dir / "manifest.json", {"resources": []})
    if not manifest["resources"]:
        _stage_manifest(course_id, root)
        manifest = _load_json(out_dir / "manifest.json", {"resources": []})

    pages_path = out_dir / "pages.jsonl"
    page_count = 0
    with pages_path.open("w", encoding="utf-8") as wf:
        for res in manifest["resources"]:
            file_path = root / res["relative_path"]
            for idx, page_text in enumerate(_extract_pages(file_path), start=1):
                page_count += 1
                payload = {
                    "page_id": f"{res['resource_id']}__P{idx}",
                    "course_id": course_id,
                    "resource_id": res["resource_id"],
                    "resource_type": res["resource_type"],
                    "file_name": res["file_name"],
                    "page_no": idx,
                    "text": page_text,
                    "tokens": len(page_text.split()),
                    "meta": {"title_guess": page_text[:20], "hash": hashlib.md5(page_text.encode()).hexdigest()[:6]},
                }
                wf.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return RunResult(True, "pages", [str(pages_path)], {"pages": page_count})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _stage_units(course_id: str, root: Path, fallback_n: int = 5) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    pages = _read_jsonl(out_dir / "pages.jsonl")
    if not pages:
        _stage_pages(course_id, root)
        pages = _read_jsonl(out_dir / "pages.jsonl")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in pages:
        grouped.setdefault(row["resource_id"], []).append(row)

    chapters = []
    chapter_no = 1
    for resource_id, resource_pages in grouped.items():
        units = []
        for i in range(0, len(resource_pages), fallback_n):
            chunk = resource_pages[i : i + fallback_n]
            unit_no = len(units) + 1
            units.append(
                {
                    "unit_id": f"{course_id}__CH{chapter_no:02d}_U{unit_no:02d}",
                    "unit_name": f"Unit {unit_no}",
                    "page_refs": [
                        {
                            "resource_id": resource_id,
                            "page_start": chunk[0]["page_no"],
                            "page_end": chunk[-1]["page_no"],
                        }
                    ],
                }
            )
        chapters.append(
            {
                "chapter_id": f"{course_id}__CH{chapter_no:02d}",
                "chapter_name": f"Chapter {chapter_no}",
                "units": units,
            }
        )
        chapter_no += 1

    payload = {"course_id": course_id, "chapters": chapters}
    units_path = out_dir / "units.json"
    _write_json(units_path, payload)
    return RunResult(True, "units", [str(units_path)], {"chapters": len(chapters)})


def _stage_kps(course_id: str, root: Path) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    units = _load_json(out_dir / "units.json", {"chapters": []})
    if not units["chapters"]:
        _stage_units(course_id, root)
        units = _load_json(out_dir / "units.json", {"chapters": []})

    kps = []
    for chapter in units["chapters"]:
        for unit in chapter["units"]:
            kp_slug = _slugify(unit["unit_name"]).upper()
            kps.append(
                {
                    "kp_id": f"{unit['unit_id']}__{kp_slug}",
                    "chapter_id": chapter["chapter_id"],
                    "unit_id": unit["unit_id"],
                    "kp_name": unit["unit_name"],
                    "summary": f"Auto generated summary for {unit['unit_name']}",
                    "keywords": [unit["unit_name"].lower(), "auto"],
                    "importance": "should",
                    "difficulty": 2,
                    "citations": [],
                }
            )

    payload = {"course_id": course_id, "kps": kps}
    kps_path = out_dir / "kps.json"
    _write_json(kps_path, payload)
    return RunResult(True, "kps", [str(kps_path)], {"kps": len(kps)})


def _stage_citations(course_id: str, root: Path) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    pages = _read_jsonl(out_dir / "pages.jsonl")
    kps_payload = _load_json(out_dir / "kps.json", {"kps": []})
    if not pages:
        _stage_pages(course_id, root)
        pages = _read_jsonl(out_dir / "pages.jsonl")
    if not kps_payload["kps"]:
        _stage_kps(course_id, root)
        kps_payload = _load_json(out_dir / "kps.json", {"kps": []})

    low_conf = {"citations": [], "question_links": []}
    by_unit: dict[str, list[dict[str, Any]]] = {}
    units = _load_json(out_dir / "units.json", {"chapters": []})
    for chapter in units["chapters"]:
        for unit in chapter["units"]:
            rows = []
            for pref in unit["page_refs"]:
                rows.extend(
                    [
                        p
                        for p in pages
                        if p["resource_id"] == pref["resource_id"] and pref["page_start"] <= p["page_no"] <= pref["page_end"]
                    ]
                )
            by_unit[unit["unit_id"]] = rows

    for kp in kps_payload["kps"]:
        candidates = by_unit.get(kp["unit_id"], [])[:3]
        if not candidates:
            continue
        conf = 0.8 if len(candidates) > 1 else 0.6
        kp["citations"] = [
            {
                "resource_id": c["resource_id"],
                "page_start": c["page_no"],
                "page_end": c["page_no"],
                "confidence": conf,
            }
            for c in candidates[:2]
        ]
        if conf < 0.75:
            low_conf["citations"].append(
                {
                    "kp_id": kp["kp_id"],
                    "confidence": conf,
                    "candidate_pages": [c["page_id"] for c in candidates],
                }
            )

    _write_json(out_dir / "kps.json", kps_payload)
    low_path = out_dir / "reports" / "low_confidence.json"
    _write_json(low_path, low_conf)
    return RunResult(True, "citations", [str(out_dir / "kps.json"), str(low_path)], {"low_conf_citations": len(low_conf["citations"])})


def _stage_questions(course_id: str, root: Path) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    pages = _read_jsonl(out_dir / "pages.jsonl")
    kps = _load_json(out_dir / "kps.json", {"kps": []})["kps"]
    questions = []
    counter = 1
    for row in pages:
        if row["resource_type"] != "questions":
            continue
        question_id = f"{course_id}__Q__{_slugify(Path(row['file_name']).stem)}__{counter:04d}"
        kp_links = []
        if kps:
            kp_links.append({"kp_id": kps[min(counter - 1, len(kps) - 1)]["kp_id"], "confidence": 0.7})
        questions.append(
            {
                "question_id": question_id,
                "type": "short",
                "stem": row["text"][:200],
                "answer": "",
                "explanation": "",
                "difficulty": 2,
                "source": {
                    "kind": "pastpaper",
                    "year": None,
                    "file_name": row["file_name"],
                    "page_no": row["page_no"],
                },
                "kp_links": kp_links,
            }
        )
        counter += 1

    payload = {"course_id": course_id, "questions": questions}
    q_path = out_dir / "questions.json"
    _write_json(q_path, payload)

    low_path = out_dir / "reports" / "low_confidence.json"
    low_conf = _load_json(low_path, {"citations": [], "question_links": []})
    for q in questions:
        if not q["kp_links"] or q["kp_links"][0]["confidence"] < 0.75:
            low_conf["question_links"].append(
                {"question_id": q["question_id"], "confidence": q["kp_links"][0]["confidence"] if q["kp_links"] else 0.0}
            )
    _write_json(low_path, low_conf)
    return RunResult(True, "questions", [str(q_path), str(low_path)], {"questions": len(questions)})


def _stage_export(course_id: str, root: Path) -> RunResult:
    out_dir = _course_out_dir(root, course_id)
    units = _load_json(out_dir / "units.json", {"chapters": []})
    kps = _load_json(out_dir / "kps.json", {"kps": []})["kps"]

    unit_to_kps: dict[str, list[dict[str, str]]] = {}
    for kp in kps:
        unit_to_kps.setdefault(kp["unit_id"], []).append({"kp_id": kp["kp_id"]})

    chapters = []
    for chapter in units["chapters"]:
        chapter_units = []
        for unit in chapter["units"]:
            chapter_units.append(
                {
                    "unit_id": unit["unit_id"],
                    "unit_name": unit["unit_name"],
                    "kps": unit_to_kps.get(unit["unit_id"], []),
                }
            )
        chapters.append(
            {
                "chapter_id": chapter["chapter_id"],
                "chapter_name": chapter["chapter_name"],
                "units": chapter_units,
            }
        )

    kb = {
        "schema_version": "1.0.0",
        "course": {"course_id": course_id, "course_name": course_id, "chapters": chapters},
    }

    kb_path = out_dir / "kb.json"
    _write_json(kb_path, kb)
    valid = validate_kb(kb, root / "KB_SCHEMA.json")
    if not valid:
        raise PipelineError("Export failed: kb.json does not pass KB_SCHEMA.json validation")

    return RunResult(True, "export", [str(kb_path)], {"chapters": len(chapters), "kps": len(kps)})


def validate_kb(kb_payload: dict[str, Any], schema_path: Path) -> bool:
    schema = _load_json(schema_path, None)
    if not schema:
        return True
    try:
        import jsonschema

        jsonschema.validate(instance=kb_payload, schema=schema)
        return True
    except ImportError:
        return True
    except Exception:
        return False


def _write_pipeline_state(course_id: str, stage: str, stats: dict[str, int], root: Path) -> None:
    state_path = _course_out_dir(root, course_id) / "pipeline_state.json"
    state = {
        "course_id": course_id,
        "last_stage": stage,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    _write_json(state_path, state)
