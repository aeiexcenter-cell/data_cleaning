# Data Cleaning Pipeline（v1）

这个项目用于把课程资料（slides/textbook/notes/questions/kp_seed）清洗为可导入的 `kb.json`。

## 1. 你需要先配置什么（必读）

### 1.1 Python 环境
- 建议 Python `3.10+`
- 安装依赖（至少）：

```bash
pip install streamlit jsonschema
```

> 说明：
> - `streamlit` 用于 GUI。
> - `jsonschema` 用于导出 `kb.json` 时做 schema 校验。

### 1.2 LLM / API 配置（如果你启用大模型能力）
在 GUI 的 **Config 页面**里你可以设置：
- `provider`（openai/deepseek/custom）
- `model`
- `api_base`（可选）
- `api_key_env`（环境变量名）

你还需要在系统环境变量中设置 API Key，例如：

```bash
export OPENAI_API_KEY="你的key"
```

如果你在 Config 里把 `api_key_env` 改成其他名字（例如 `DEEPSEEK_API_KEY`），就需要对应设置：

```bash
export DEEPSEEK_API_KEY="你的key"
```

### 1.3 输入目录约定

```text
data/<COURSE_ID>/sources/{slides,textbook,notes,questions,kp_seed}
```

GUI 会自动帮你上传到对应目录。

---

## 2. 一键流程（给非技术同学）

启动 GUI：

```bash
streamlit run app/studio.py
```

按页面顺序操作：

1. **Files**：上传并分类文件，点击“生成/刷新 manifest”
2. **Config**：填写参数（清洗、切分、KP、citations、questions、LLM）并保存配置
3. **Run**：选择阶段运行（推荐先 `manifest/pages/units`，最后 `export`）
4. **Review**：查看 `low_confidence`，手动改 KP citations 和 Question kp_links
5. **Export**：生成并下载 `kb.json`

---

## 3. CLI（开发者调试）

```bash
python -m pipeline.main AI_INTRO --stage export --root .
```

可选阶段：
- `manifest`
- `pages`
- `units`
- `kps`
- `citations`
- `questions`
- `export`

---

## 4. 固定输出文件

输出在：

```text
out/<COURSE_ID>/
```

核心文件：
- `manifest.json`
- `pages.jsonl`
- `units.json`
- `kps.json`
- `questions.json`
- `reports/low_confidence.json`
- `kb.json`
- `pipeline_state.json`

`kb.json` 会按 `KB_SCHEMA.json` 校验。
