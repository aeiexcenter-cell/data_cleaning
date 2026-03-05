from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

from pipeline.engine import STAGES, run_stage

ROOT = Path(".")
SOURCE_BUCKETS = ["slides", "textbook", "notes", "questions", "kp_seed"]


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _course_dirs(course_id: str) -> tuple[Path, Path]:
    data_dir = ROOT / "data" / course_id / "sources"
    out_dir = ROOT / "out" / course_id
    return data_dir, out_dir


def _load_snapshot(out_dir: Path) -> dict[str, Any]:
    snapshot = out_dir / "pipeline.yaml.snapshot"
    if snapshot.exists():
        try:
            return json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_snapshot(out_dir: Path, config: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pipeline.yaml.snapshot").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_config_form(defaults: dict[str, Any]) -> dict[str, Any]:
    st.markdown("### 基础清洗")
    c1, c2, c3 = st.columns(3)
    remove_header_footer = c1.checkbox("去页眉页脚", value=defaults.get("cleaning", {}).get("remove_header_footer", True))
    merge_bullets = c2.checkbox("合并 bullet", value=defaults.get("cleaning", {}).get("merge_bullets", True))
    drop_toc = c3.checkbox("丢弃目录页", value=defaults.get("cleaning", {}).get("drop_toc_pages", True))

    st.markdown("### 章节切分")
    c4, c5 = st.columns(2)
    heading_pattern = c4.text_input(
        "标题识别 pattern（正则）",
        value=defaults.get("segmentation", {}).get("heading_pattern", r"第\\d+章|\\d+\\.\\d+"),
    )
    fallback_n = c5.number_input("fallback N 页一组", min_value=1, value=int(defaults.get("segmentation", {}).get("fallback_pages", 5)))

    st.markdown("### KP 与引用")
    c6, c7, c8 = st.columns(3)
    kp_mode = c6.selectbox("KP 模式", ["seeded", "auto"], index=0 if defaults.get("kp", {}).get("mode", "seeded") == "seeded" else 1)
    dedup_threshold = c7.slider("KP 去重阈值", min_value=0.0, max_value=1.0, value=float(defaults.get("kp", {}).get("dedup_threshold", 0.85)), step=0.01)
    citations_top_k = c8.number_input("citations top_k", min_value=1, value=int(defaults.get("citations", {}).get("top_k", 5)))
    citation_threshold = st.slider(
        "citation 低置信度阈值", min_value=0.0, max_value=1.0, value=float(defaults.get("citations", {}).get("confidence_threshold", 0.75)), step=0.01
    )

    st.markdown("### 题目抽取")
    c9, c10 = st.columns(2)
    extract_questions = c9.checkbox("启用题目抽取", value=defaults.get("questions", {}).get("enabled", True))
    generate_questions = c10.checkbox("启用 AI 补题", value=defaults.get("questions", {}).get("generate", False))
    blueprint = st.text_area("题型蓝图（JSON）", value=json.dumps(defaults.get("questions", {}).get("blueprint", {"short": 5}), ensure_ascii=False, indent=2), height=120)

    st.markdown("### LLM 配置（给开发者/管理员）")
    c11, c12, c13 = st.columns(3)
    provider = c11.selectbox("LLM Provider", ["openai", "deepseek", "custom"], index=["openai", "deepseek", "custom"].index(defaults.get("llm", {}).get("provider", "openai")))
    model = c12.text_input("Model", value=defaults.get("llm", {}).get("model", "gpt-4o-mini"))
    api_base = c13.text_input("API Base（可选）", value=defaults.get("llm", {}).get("api_base", ""))
    api_key_env = st.text_input("API Key 环境变量名", value=defaults.get("llm", {}).get("api_key_env", "OPENAI_API_KEY"))

    try:
        parsed_blueprint = json.loads(blueprint)
    except Exception:
        parsed_blueprint = {"raw": blueprint}

    return {
        "cleaning": {
            "remove_header_footer": remove_header_footer,
            "merge_bullets": merge_bullets,
            "drop_toc_pages": drop_toc,
        },
        "segmentation": {"heading_pattern": heading_pattern, "fallback_pages": fallback_n},
        "kp": {"mode": kp_mode, "dedup_threshold": dedup_threshold},
        "citations": {"top_k": citations_top_k, "confidence_threshold": citation_threshold},
        "questions": {"enabled": extract_questions, "generate": generate_questions, "blueprint": parsed_blueprint},
        "llm": {
            "provider": provider,
            "model": model,
            "api_base": api_base,
            "api_key_env": api_key_env,
            "api_key_configured": bool(os.getenv(api_key_env)),
        },
    }


st.set_page_config(page_title="Pipeline Studio", layout="wide")
st.title("Pipeline Studio（面向非技术同学）")
st.caption("按 1) 上传文件 → 2) 配置参数 → 3) 运行阶段 → 4) 抽检修订 → 5) 导出 kb.json 的流程操作")

course_id = st.text_input("课程 ID（示例：AI_INTRO）", value="AI_INTRO").strip().upper()
data_dir, out_dir = _course_dirs(course_id)
pages = st.tabs(["Dashboard", "Files", "Config", "Run", "Review", "Export"])

with pages[0]:
    st.subheader("Dashboard")
    st.markdown("- 当前课程目录：`data/<course_id>/sources/...`  \n- 当前产出目录：`out/<course_id>/...`")
    state_path = out_dir / "pipeline_state.json"
    if state_path.exists():
        st.success("已存在最近一次运行状态")
        st.json(_load_json(state_path, {}))
    else:
        st.info("还没有运行记录，请先去 Files 上传文件并生成 manifest。")

with pages[1]:
    st.subheader("Files：上传并分类")
    data_dir.mkdir(parents=True, exist_ok=True)

    bucket = st.selectbox("文件分类", SOURCE_BUCKETS)
    uploaded = st.file_uploader("拖拽或选择文件（可多选）", accept_multiple_files=True)
    if st.button("保存上传文件", type="primary"):
        if not uploaded:
            st.warning("请先选择文件")
        else:
            target = data_dir / bucket
            target.mkdir(parents=True, exist_ok=True)
            for f in uploaded:
                (target / f.name).write_bytes(f.getbuffer())
            st.success(f"已保存 {len(uploaded)} 个文件到 {bucket}")

    st.markdown("### 当前文件概览")
    for b in SOURCE_BUCKETS:
        files = sorted([p.name for p in (data_dir / b).glob("*") if p.is_file()])
        st.write(f"**{b}** ({len(files)})")
        if files:
            st.code("\n".join(files), language="text")

    if st.button("生成/刷新 manifest"):
        result = run_stage(course_id, "manifest")
        st.success("manifest 生成完成")
        st.json(result.__dict__)

    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        st.markdown("### manifest 预览")
        st.json(_load_json(manifest_path, {}))

with pages[2]:
    st.subheader("Config：完整配置向导")
    defaults = _load_snapshot(out_dir)
    config = _build_config_form(defaults)

    col_a, col_b = st.columns(2)
    if col_a.button("保存配置", type="primary"):
        _save_snapshot(out_dir, config)
        st.success("已保存到 out/<course_id>/pipeline.yaml.snapshot")
    if col_b.button("加载已有配置"):
        st.json(_load_snapshot(out_dir))

    st.markdown("### 当前配置 JSON")
    st.json(config)

with pages[3]:
    st.subheader("Run：运行阶段")
    stage = st.selectbox("选择运行阶段", STAGES, index=STAGES.index("export"))
    if st.button("开始运行", type="primary"):
        result = run_stage(course_id, stage)
        st.success(f"阶段 {stage} 运行成功")
        st.json(result.__dict__)

    st.markdown("### 关键产物检查")
    expected = [
        "manifest.json",
        "pages.jsonl",
        "units.json",
        "kps.json",
        "questions.json",
        "reports/low_confidence.json",
        "kb.json",
        "pipeline_state.json",
    ]
    for rel in expected:
        p = out_dir / rel
        st.write(f"{'✅' if p.exists() else '⬜'} {rel}")

with pages[4]:
    st.subheader("Review：低置信度审核 + 手动修订")
    low_path = out_dir / "reports" / "low_confidence.json"
    kps_path = out_dir / "kps.json"
    q_path = out_dir / "questions.json"

    low_conf = _load_json(low_path, {"citations": [], "question_links": []})
    st.markdown("#### 低置信度队列")
    st.json(low_conf)

    st.markdown("#### 编辑 KP citations")
    kps_payload = _load_json(kps_path, {"course_id": course_id, "kps": []})
    kp_ids = [kp["kp_id"] for kp in kps_payload.get("kps", [])]
    if kp_ids:
        kp_id = st.selectbox("选择 KP", kp_ids)
        kp_obj = next(k for k in kps_payload["kps"] if k["kp_id"] == kp_id)
        kp_obj["kp_name"] = st.text_input("kp_name", kp_obj.get("kp_name", ""))
        kp_obj["summary"] = st.text_area("summary", kp_obj.get("summary", ""), height=80)
        citations_text = st.text_area("citations(JSON array)", json.dumps(kp_obj.get("citations", []), ensure_ascii=False, indent=2), height=150)
        if st.button("保存 KP 修改"):
            try:
                kp_obj["citations"] = json.loads(citations_text)
                _save_json(kps_path, kps_payload)
                st.success("KP 已保存")
            except Exception as exc:
                st.error(f"citations JSON 解析失败: {exc}")
    else:
        st.info("暂无 kps.json，请先运行 kps/citations 阶段")

    st.markdown("#### 编辑 Question 归因")
    questions_payload = _load_json(q_path, {"course_id": course_id, "questions": []})
    q_ids = [q["question_id"] for q in questions_payload.get("questions", [])]
    if q_ids:
        q_id = st.selectbox("选择 Question", q_ids)
        q_obj = next(q for q in questions_payload["questions"] if q["question_id"] == q_id)
        q_obj["stem"] = st.text_area("stem", q_obj.get("stem", ""), height=100)
        kp_links_text = st.text_area("kp_links(JSON array)", json.dumps(q_obj.get("kp_links", []), ensure_ascii=False, indent=2), height=120)
        if st.button("保存 Question 修改"):
            try:
                q_obj["kp_links"] = json.loads(kp_links_text)
                _save_json(q_path, questions_payload)
                st.success("Question 已保存")
            except Exception as exc:
                st.error(f"kp_links JSON 解析失败: {exc}")
    else:
        st.info("暂无 questions.json，请先运行 questions 阶段")

with pages[5]:
    st.subheader("Export")
    if st.button("生成 kb.json", type="primary"):
        result = run_stage(course_id, "export")
        st.success("导出完成")
        st.json(result.__dict__)

    kb_path = out_dir / "kb.json"
    if kb_path.exists():
        payload = kb_path.read_text(encoding="utf-8")
        st.download_button("下载 kb.json", data=payload, file_name="kb.json", mime="application/json")
        st.json(json.loads(payload))
    else:
        st.info("尚未导出 kb.json")
