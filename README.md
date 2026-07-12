# Master's Prep AI / AI 考研助手平台

Master's Prep AI 是一个面向考研备考全过程的智能学习辅助平台。它把学生画像、诊断评估、学习计划、知识库讲解、专项练习、错题沉淀、复习队列和学习看板整合到同一个 Web 工作区中，帮助备考用户持续完成“诊断、学习、练习、反馈、调整”的闭环。

本仓库是团队项目主仓库，后续开发、测试、提交和部署都以 `3171381144/Master-s-Prep-AI` 为准。

## 核心能力

- 用户体系：本地注册、登录、退出、会话 Cookie、首个管理员初始化，以及按 `user_id` 隔离学习数据。
- 考研助手：初始化学生画像，创建诊断，确认诊断报告，生成阶段计划和今日任务，动态更新任务状态。
- 内容库：读取高数知识树、知识点详情、公式、易错点、样题和 AI 讲解上下文。
- 练习闭环：支持专项练习、错题二刷、图片答案提交、AI 辅助判分、错题本和复习队列。
- 学习看板：展示完成率、正确率、错题数、今日复习、掌握度分布和近期学习状态。
- 通用 AI 能力：保留多 Agent、RAG、LLM Provider、Web/API、CLI、知识库、笔记和数学动画等基础能力。

## 技术栈

- 后端：Python 3.11+、FastAPI、Pydantic、SQLite、Typer、RAG 服务、LLM Provider 抽象。
- 前端：Next.js 16、React 19、TypeScript、Tailwind CSS。
- 数据：本地 SQLite、用户工作区、知识库目录、附件与输出目录。
- 测试：pytest、Node 测试脚本、Next.js build、GitHub Actions。

## 目录结构

```text
master_prep_ai/          后端应用、API、Agent、RAG、考研业务模块
master_prep_ai_cli/      命令行入口
web/                     Next.js 前端工作区
scripts/                 启动、配置、迁移和维护脚本
requirements/            分层依赖清单
tests/                   后端测试与业务回归测试
assets/                  项目静态资源
```

## 快速开始

### 1. 安装后端依赖

```powershell
python -m pip install -e .[server]
```

开发和测试场景可安装：

```powershell
python -m pip install -e .[dev]
```

### 2. 安装前端依赖

```powershell
cd web
npm install
cd ..
```

### 3. 配置环境变量

复制 `.env.example` 或 `.env.example_CN` 为 `.env`，再按本地模型或 API 服务填写：

```powershell
Copy-Item .env.example .env
```

常用字段包括：

- `BACKEND_PORT`
- `FRONTEND_PORT`
- `LLM_BINDING`
- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_HOST`
- `EMBEDDING_BINDING`
- `EMBEDDING_MODEL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_HOST`

`.env` 默认不应提交。不要把真实 API Key、账号密码或个人学习数据提交到仓库。

### 4. 启动 Web 应用

```powershell
python scripts/start_web.py
```

默认会同时启动：

- 后端：`http://localhost:8000`，或 `.env` 中配置的 `BACKEND_PORT`
- 前端：`http://localhost:3000`，或 `.env` 中配置的 `FRONTEND_PORT`

也可以分别启动：

```powershell
python -m master_prep_ai.api.run_server
cd web
npm run dev
```

## CLI

安装后可以使用统一命令：

```powershell
master-prep-ai chat
master-prep-ai run chat "解释傅里叶变换" -l zh
master-prep-ai serve --port 8001
```

Provider auth (`openai-codex` OAuth login; `github-copilot` validates an existing Copilot auth session):

```powershell
master-prep-ai provider login openai-codex
master-prep-ai provider login github-copilot
```

## 数据库与内容库

考研高数内容库默认读取项目内的相对路径：

```text
data/math_content.sqlite
```

也可以通过环境变量指定 `data` 下的相对路径：

```powershell
$env:KAOYAN_CONTENT_DB = "math_content.sqlite"
```

学习行为数据默认写入：

```text
data/user/kaoyan_learning.sqlite
```

也可以通过环境变量指定：

```powershell
$env:KAOYAN_APP_DB = "E:\path\to\kaoyan_learning.sqlite"
```

## PDF 与 LaTeX 包

“填写/综合题 PDF”功能使用本机 XeLaTeX。项目会在生成 PDF 前尝试为 MiKTeX 自动安装所需 LaTeX 包，默认包列表在 `master_prep_ai/kaoyan/pdf_renderer.py` 的 `_DEFAULT_LATEX_PACKAGES` 中。

可以提前预热安装：

```powershell
python scripts/setup_latex.py
```

常用配置：

```powershell
$env:KAOYAN_LATEX_AUTO_INSTALL = "true"
$env:KAOYAN_LATEX_TIMEOUT = "180"
$env:KAOYAN_LATEX_INSTALL_TIMEOUT = "300"
```

如果 `xelatex.exe` 不在 PATH 中，可以设置：

```powershell
$env:KAOYAN_XELATEX_PATH = "C:\path\to\xelatex.exe"
```

## 主要 API

考研业务后端统一挂载在 `/api/v1/kaoyan` 下，主要接口包括：

- `POST /profile/init`：初始化或更新学生画像。
- `GET /profile/me`：读取当前学生画像。
- `POST /diagnostic/session`：创建诊断会话。
- `POST /diagnostic/{session_id}/submit`：提交诊断并生成画像草案。
- `GET /diagnostic/reports`：读取诊断报告历史。
- `PATCH /diagnostic/reports/{report_id}/confirm`：确认诊断报告并更新画像。
- `POST /plans/generate`：生成学习计划和今日任务。
- `GET /tasks/today`：读取今日任务。
- `PATCH /tasks/{task_id}/status`：更新任务状态。
- `GET /content/knowledge-tree`：读取高数知识点树。
- `GET /content/knowledge/{knowledge_id}`：读取知识点详情。
- `POST /chat-context`：生成知识点或题目的 AI 讲解上下文。
- `POST /practice/session`：创建专项练习或错题二刷。
- `POST /practice/{session_id}/submit`：提交练习并生成错题、掌握度和复习项。
- `GET /wrong-questions`：读取错题本。
- `GET /reviews/today`：读取今日复习队列。
- `POST /reviews/{review_id}/submit`：提交复习结果。
- `GET /dashboard/summary`：读取学习看板摘要。

## 测试

后端核心测试：

```powershell
python -m compileall master_prep_ai master_prep_ai_cli tests
python -m pytest tests/kaoyan tests/api/test_auth_router.py tests/api/test_outputs_router.py tests/services/session/test_user_isolation.py
```

前端测试与构建：

```powershell
cd web
npm run test:node
npm run build
```

## 安全与提交说明

- 不提交 `.env`、真实 API Key、用户数据库、运行日志、上传文件、输出文件、`node_modules/`、`.next/` 或缓存目录。
- 当前 Git 远端 `ours` 指向团队仓库：`https://github.com/3171381144/Master-s-Prep-AI.git`。
- 提交前建议执行静态检索、后端测试、前端 Node 测试和前端构建，确认重命名后功能仍可运行。

## License

本项目保留 Apache-2.0 许可证。详见 `LICENSE`。
