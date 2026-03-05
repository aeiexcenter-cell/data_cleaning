from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from pipeline.engine import STAGES, run_stage

ROOT = Path(".")

st.set_page_config(page_title="Pipeline Studio", layout="wide")
st.title("Pipeline Studio (MVP)")

course_id = st.text_input("Course ID", value="AI_INTRO")
out_dir = ROOT / "out" / course_id

pages = st.tabs(["Dashboard", "Files", "Config", "Run", "Review", "Export"])

with pages[0]:
    st.subheader("Dashboard")
    state_path = out_dir / "pipeline_state.json"
    if state_path.exists():
        st.json(json.loads(state_path.read_text(encoding="utf-8")))
    else:
        st.info("No pipeline state yet.")

with pages[1]:
    st.subheader("Files")
    if st.button("生成 manifest"):
        result = run_stage(course_id, "manifest")
        st.success(result.message or "manifest generated")
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        st.json(json.loads(manifest_path.read_text(encoding="utf-8")))

with pages[2]:
    st.subheader("Config")
    fallback_n = st.number_input("fallback N pages", min_value=1, value=5)
    config = {
        "segmentation": {"fallback_pages": fallback_n},
        "kp": {"mode": "seeded", "dedup_threshold": 0.85},
        "citations": {"top_k": 5, "confidence_threshold": 0.75},
    }
    if st.button("保存配置"):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "pipeline.yaml.snapshot").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success("配置已保存")
    st.json(config)

with pages[3]:
    st.subheader("Run")
    stage = st.selectbox("Run stage", STAGES, index=STAGES.index("export"))
    if st.button("运行", type="primary"):
        result = run_stage(course_id, stage)
        st.success("成功")
        st.json(result.__dict__)

with pages[4]:
    st.subheader("Review")
    low_path = out_dir / "reports" / "low_confidence.json"
    if low_path.exists():
        st.json(json.loads(low_path.read_text(encoding="utf-8")))
    else:
        st.info("No low confidence entries.")

with pages[5]:
    st.subheader("Export")
    kb_path = out_dir / "kb.json"
    if st.button("导出 kb.json"):
        result = run_stage(course_id, "export")
        st.success("kb.json generated")
        st.json(result.__dict__)
    if kb_path.exists():
        st.download_button("下载 kb.json", data=kb_path.read_text(encoding="utf-8"), file_name="kb.json")
        st.json(json.loads(kb_path.read_text(encoding="utf-8")))
