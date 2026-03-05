# Data Cleaning Pipeline (v1 MVP)

实现了课程资料清洗流水线与 Streamlit Studio 的最小可用版本，覆盖：

- `manifest/pages/units/kps/citations/questions/export` 全阶段执行
- 固定产物：`manifest.json`, `pages.jsonl`, `units.json`, `kps.json`, `questions.json`, `reports/low_confidence.json`, `kb.json`, `pipeline_state.json`
- `kb.json` 通过 `KB_SCHEMA.json` 校验后导出

## 快速开始

```bash
python -m pipeline.main AI_INTRO --stage export --root .
```

## Streamlit

```bash
streamlit run app/studio.py
```

## 目录约定

输入目录：

```text
data/<COURSE_ID>/sources/{slides,textbook,notes,questions,kp_seed}
```

输出目录：

```text
out/<COURSE_ID>/
```

