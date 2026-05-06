# Master's Prep AI - AI考研助手平台

Master's Prep AI 是一个面向考研备考全过程的智能学习辅助平台。项目基于 DeepTutor 的 Agent-native、RAG、Web 工作区和多模态能力进行二次开发，当前重点落地“AI考研助手”核心学习闭环：画像、诊断、计划、学习、练习、错题、复习、反馈和动态调整。

本仓库是我们团队的项目仓库，不是 HKUDS/DeepTutor 上游仓库。后续开发、提交和部署都应以本仓库为准。

## 项目目标

平台希望把考研备考中分散的资料、计划、练习和复盘整合成一个可持续运行的学习系统：

- 根据目标院校、目标专业、考试日期、每日学习时长和基础水平生成学生画像。
- 通过轻量诊断或深度诊断识别薄弱知识点，并形成画像草案。
- 生成阶段计划、今日任务和任务状态记录。
- 基于高数知识库展示知识点、公式、易错点、样题和讲解上下文。
- 支持专项练习、错题二刷、AI 辅助判分和图片答案提交。
- 将错题自动沉淀到错题本和复习队列。
- 通过看板展示完成率、正确率、错题数、复习待办和掌握度分布。

## 当前核心能力

### 1. 用户与权限

- 本地用户注册、登录、退出和会话 Cookie。
- 首个管理员初始化。
- 学习数据按 `user_id` 隔离。
- 前端工作区登录守卫。

相关代码：

- `deeptutor/auth.py`
- `deeptutor/api/routers/auth.py`
- `web/context/AuthContext.tsx`
- `web/components/auth/WorkspaceAuthGate.tsx`
- `web/app/login/page.tsx`
- `web/app/setup/page.tsx`

### 2. AI考研助手业务模块

后端统一挂载在 `/api/v1/kaoyan` 下，主要包括：

- `POST /profile/init`：初始化或更新学生画像。
- `GET /profile/me`：读取当前学生画像。
- `POST /diagnostic/session`：创建入门诊断。
- `POST /diagnostic/{session_id}/submit`：提交诊断并生成画像草案。
- `GET /diagnostic/reports`：读取诊断报告历史。
- `PATCH /diagnostic/reports/{report_id}/confirm`：确认诊断报告并更新画像。
- `POST /plans/generate`：生成学习计划和今日任务。
- `GET /tasks/today`：读取今日任务。
- `PATCH /tasks/{task_id}/status`：更新任务状态。
- `GET /content/knowledge-tree`：读取高数知识点树。
- `GET /content/knowledge/{knowledge_id}`：读取知识点详情。
- `POST /chat-context`：为知识点或题目生成 AI 讲解上下文。
- `POST /practice/session`：创建专项练习或错题二刷。
- `POST /practice/{session_id}/submit`：提交练习并生成错题、掌握度和复习项。
- `GET /wrong-questions`：读取错题本。
- `GET /reviews/today`：读取今日复习队列。
- `POST /reviews/{review_id}/submit`：提交复习结果。
- `GET /dashboard/summary`：读取学习看板摘要。

相关代码：

- `deeptutor/api/routers/kaoyan.py`
- `deeptutor/kaoyan/content_store.py`
- `deeptutor/kaoyan/learning_store.py`
- `deeptutor/kaoyan/diagnostic.py`
- `deeptutor/kaoyan/planner.py`
- `deeptutor/kaoyan/practice.py`
- `deeptutor/kaoyan/review.py`
- `deeptutor/kaoyan/chat_context.py`
- `deeptutor/kaoyan/ai_service.py`

### 3. 前端考研工作区

前端提供一个考研助手工作区页面，包含驾驶舱、知识库、练习、错题、诊断报告和复习队列。

相关代码：

- `web/app/(workspace)/kaoyan/page.tsx`
- `web/lib/kaoyan-api.ts`
- `web/lib/kaoyan-types.ts`
- `web/app/api/v1/[...path]/route.ts`
- `web/app/api/v1/auth/[...path]/route.ts`

## 技术栈

- 后端：Python 3.11+、FastAPI、Pydantic、SQLite、RAG 服务、LLM Provider 抽象。
- 前端：Next.js 16、React 19、TypeScript、Tailwind CSS。
- AI 能力：可配置 LLM、Embedding、RAG、数学题讲解、诊断生成、AI 辅助判分。
- 数据存储：本地 SQLite、用户工作区、知识库目录、附件与输出目录。

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

复制 `.env.example` 或 `.env.example_CN` 为 `.env`，按本地模型或 API 服务填写：

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

注意：`.env` 默认被 `.gitignore` 忽略，不要提交真实 API Key。

### 4. 启动 Web 应用

```powershell
python scripts/start_web.py
```

默认会同时启动：

- 后端：`http://localhost:8000` 或 `.env` 中配置的 `BACKEND_PORT`
- 前端：`http://localhost:3000` 或 `.env` 中配置的 `FRONTEND_PORT`

也可以分别启动：

```powershell
python -m deeptutor.api.run_server
cd web
npm run dev
```

## 数据与内容库

当前考研高数内容库默认读取项目外层的：

```text
../math_content.sqlite
```

也可以通过环境变量指定：

```powershell
$env:KAOYAN_CONTENT_DB = "E:\path\to\math_content.sqlite"
```

学习行为数据默认写入：

```text
data/user/kaoyan_learning.sqlite
```

可通过环境变量指定：

```powershell
$env:KAOYAN_APP_DB = "E:\path\to\kaoyan_learning.sqlite"
```

## 测试

后端核心测试：

```powershell
python -m pytest tests/kaoyan tests/api/test_auth_router.py tests/api/test_outputs_router.py tests/services/session/test_user_isolation.py
```

前端 Node 测试：

```powershell
cd web
npm run test:node
```

## 团队分工建议

当前项目建议按功能域分三条线并行开发：

- 成员 A：画像诊断、学习计划、任务驾驶舱、动态重排和看板。
- 成员 B：内容库、知识点树、资料结构化、RAG/AI 讲解上下文。
- 成员 C：练习组卷、提交判分、错题复盘、复习队列和冲刺模拟预留。

详细分工文档位于工作区外层：

```text
E:\Group-projects\Master's Prep AI\DeepTutor\output\doc\AI考研助手三人功能分工与接口接入方案.docx
```

## 仓库安全说明

- 不要提交 `.env`、真实 API Key、用户数据库、知识库运行数据、上传文件和输出文件。
- `data/`、`output/`、`node_modules/`、`.next/` 等目录已在 `.gitignore` 中忽略。
- 当前远端应推送到团队仓库 `3171381144/Master-s-Prep-AI`，不要推送到上游 `HKUDS/DeepTutor`。

## 项目来源说明

本项目基于 DeepTutor 进行二次开发，保留其 Apache-2.0 许可和部分通用能力。我们在此基础上增加了考研助手业务模块、用户认证、用户数据隔离、高数内容库接入、考研学习闭环页面和相关测试。
