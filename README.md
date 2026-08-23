# 企业智能 IT/HR 助手（Agent 应用）

一个**可直接部署到企业内部**的智能助手：员工用自然语言问 IT/HR 问题，Agent 通过
**RAG 检索企业制度文档 + 调用业务工具（建工单 / 查资产 / 查假期 / 转人工）** 给出带出处的可信答复。

架构亮点：**双模型分级路由** —— 简单问题（问候 / 自我介绍）由轻量小模型秒回，
复杂问题才交给主模型走 RAG + 工具链路，兼顾成本与延迟。

---

## 一、架构图

```
用户消息
  │
  ▼
[意图路由 router] ──(SMALL_MODEL: Qwen2.5-7B, 不思考)──► 分类 simple / complex
  │                                            │
  ├─ simple ─► 小模型直答（自我介绍 / 闲聊 / 速答）            ★SSE 流式
  │
  └─ complex ─► [主 Agent | CHAT_MODEL: DeepSeek-V3]
                   ├─ RAG 检索制度文档（Chroma + bge-m3 批量嵌入）
                   ├─ 工具调用（工单 / 资产 / 假期 / 转人工）
                   └─ 带出处答复                                      ★SSE 流式
```

- **后端**：FastAPI + Uvicorn，**全链路异步化**（AsyncOpenAI + 异步生成器 `arun`），LLM 网络 IO 不阻塞事件循环，天然支持并发请求；全部配置经 `pydantic-settings` 从 `.env` 读取（模型名零硬编码）
- **LLM**：SiliconFlow（OpenAI 兼容）统一接入，对话 / 嵌入 / 重排序三件套
- **向量库**：Chroma（本地持久化，仅文档变更时重嵌）
- **RAG 质量**：标题分段 + 滑动窗口 overlap 分块；向量召回 top_k 候选 → 交叉编码器重排序（SiliconFlow rerank）精排 top_n，rerank 不可用时自动降级
- **前端**：React 18 + Vite + TypeScript + Tailwind（明暗主题可切换），助手消息经 **react-markdown + remark-gfm** 渲染（标题/列表/表格/代码块/引用等），构建产物由 FastAPI 托管

---

## 二、本地运行（venv）

```bash
# 1. 创建并激活虚拟环境
python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # Linux/Mac

# 2. 安装依赖（国内可用镜像）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 配置密钥：复制 .env.example 为 .env，填入 SILICONFLOW_API_KEY
#    （其余模型名 / 参数已给默认值，可按需修改）

# 4. 构建前端
cd web
npm install
npm run build      # 产出 web/dist，由后端托管
cd ..

# 5. 入库知识库（首次或文档变更后）
$env:PYTHONPATH="."
python scripts/ingest.py --force

# 6. 启动服务
$env:PYTHONPATH="."
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://localhost:8000 即可使用。

> 开发态也可前后端分离：`cd web && npm run dev`，Vite 已配置 `/api` 代理到 `:8000`。

#### 端口说明（重要）
- 服务默认监听 **8000**；Docker 部署后容器已在 http://localhost:8000 提供 API + 前端。
- **不要**在容器运行时再手动起一个本地 `uvicorn --port 8000`，否则会报
  `WinError 10048 / [Errno 10048] address already in use`（端口被容器占用）。
- 若需本地调试且保留容器，请改用不同端口，二者互不冲突：
  ```bash
  # 方式 A：仅本地 uvicorn 换端口（容器仍占 8000）
  $env:PORT=8001                      # PowerShell
  # set PORT=8001                     # CMD
  python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8001

  # 方式 B：整体平移容器端口（访问 http://localhost:8001）
  $env:PORT=8001; docker compose up -d --build
  ```
  `PORT` 同时被容器启动命令与 `docker-compose.yml` 读取，改一处即可整体切换。

---

## 三、Docker 部署

```bash
# 1. 准备 .env（已含密钥与模型配置）
# 2. 构建并启动（多阶段：Node 构建前端 + Python 服务）
docker compose up --build
```

- 服务地址：http://localhost:8000
- 向量库通过卷 `./src/data/chroma` 持久化，重启无需重新嵌入
- `.env` 通过 `env_file` 注入容器，**不会打包进镜像**

---

## 四、配置项（`.env`）

| 配置 | 说明 | 默认 |
|------|------|------|
| `SILICONFLOW_API_KEY` | 硅基流动密钥（必填） | 空 |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.siliconflow.cn/v1` |
| `CHAT_MODEL` | 主模型（复杂问题） | `deepseek-ai/DeepSeek-V3` |
| `SMALL_MODEL` | 小模型（意图分类 + 简单直答） | `Qwen/Qwen2.5-7B-Instruct` |
| `EMBED_MODEL` | 嵌入模型 | `BAAI/bge-m3` |
| `ENABLE_INTENT_ROUTING` | 是否启用意图路由 | `true` |
| `EMBED_BATCH_SIZE` | 嵌入批量大小（入库加速） | `16` |
| `CHUNK_SIZE` | 单块最大字符数 | `500` |
| `CHUNK_OVERLAP` | 相邻块重叠字符数（滑动窗口） | `80` |
| `RAG_TOP_K` | 向量召回候选数（rerank 前） | `8` |
| `RAG_RERANK_TOP_N` | 重排序后保留数 | `3` |
| `RAG_SCORE_THRESHOLD` | 向量相似度阈值（召回过滤） | `0.25` |
| `ENABLE_RERANK` | 是否启用重排序 | `true` |
| `RERANK_MODEL` | 重排序模型（硅基流动） | `BAAI/bge-reranker-v2-m3` |
| `RERANK_SCORE_THRESHOLD` | 重排分数阈值 | `0.1` |
| `API_KEY` | 服务访问密钥（留空关闭校验） | 空 |
| `CORS_ORIGINS` | 跨域来源 | `*` |

> 所有模型均可在硅基流动模型广场替换，**代码不写死**。

---

## 五、API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 当前模型名 |
| GET | `/api/tools` | 工具清单 |
| POST | `/api/chat` | 对话（SSE 流式，body: `{message, session_id}`） |
| POST | `/api/ingest` | 触发知识库入库（body: `{force: bool}`） |
| POST | `/api/reset` | 清空某会话记忆 |

SSE 事件类型：`route` / `source` / `token` / `tool` / `done` / `error`

---

## 六、测试

```bash
$env:PYTHONPATH="."
pytest -q
```

覆盖：Mock 数据层、工具层、RAG 分块（含 overlap）、重排降级、意图路由、异步取消（代次令牌）、API 接口（含 SSE）。

---

## 七、面试亮点（Agent 应用开发岗）

1. **真·Agent 闭环**：RAG 检索 + Function Calling 工具编排，非单纯聊天机器人
2. **双模型分级路由**：小模型做意图识别与简单直答，主模型处理复杂任务 —— 体现成本 / 延迟优化思维（企业级关注点）
3. **工程完整度**：配置中心化（pydantic-settings）、Docker 一键部署、pytest 覆盖、SSE 流式、会话记忆
4. **可落地**：知识库与工具均对接 Mock 后端，并预留真实 HR / IT 系统接口位（`TODO(生产)` 注释）
5. **可观测 / 可解释**：前端展示路由来源（轻量速答 / 智能助手）、引用出处卡片、工具调用可视化
6. **国产化适配**：硅基流动统一 API，数据不出境，模型可热替换

---

## 八、生产接入说明（Mock → 真实系统）

工具与 Agent 逻辑**零改动**，只需把数据来源从本地 JSON 换成真实接口调用。参考实现见
`src/agent/mock_db.py` 中每个函数的 `TODO(生产)` 注释分支（已给出 HR / ITSM 系统的 `requests` 调用示例）。

接入步骤：
1. 在 `.env` 增加真实系统地址与令牌（建议用环境变量，避免硬编码）：
   ```
   HR_API_BASE=https://hr.internal.example.com/api
   HR_API_TOKEN=xxxx
   ITSM_API_BASE=https://itsm.internal.example.com/api
   ITSM_API_TOKEN=xxxx
   ```
2. 将 `mock_db.py` 中对应函数的 `TODO(生产)` 分支取消注释、接好返回字段映射。
3. 工具（`tools.py`）与 Agent（`agent.py`）无需任何修改即可生效。

> 设计要点：Agent 只依赖 `get_employee / get_assets / get_leave_balance` 的**函数签名**，
> 不关心数据来自 Mock 还是真实系统，实现了解耦，便于灰度切换与回归测试。

## 九、QQ 机器人接入（官方平台 bot.q.qq.com）

复用现有 Agent 流水线（RAG + 工具调用零改动），通过官方 WebSocket 网关把机器人接到 QQ 群/单聊。

**前置**：在 [bot.q.qq.com](https://bot.q.qq.com/) 创建机器人，拿到 `AppID` 与 `AppSecret`。

```bash
# 1. 安装依赖（新增 websockets）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 一键接入：首次运行无凭证会自动打开管理页链接，引导填写 AppID/Secret 并写回 .env
$env:PYTHONPATH="."
python scripts/connect_qqbot.py
```

脚本流程：打开管理页链接 → 填 AppID/Secret（写回 `.env`）→ 用 AppSecret 换 `access_token`（授权）
→ 连接 WSS 网关鉴权上线 → 监听 `群@消息` / `单聊消息` → 转发给 `src.agent.agent.arun()`（异步 Agent 流水线）→ 回传答复。

配置项（`.env`）：

| 配置 | 说明 | 默认 |
|------|------|------|
| `QQ_BOT_APPID` | 机器人 AppID | 空 |
| `QQ_BOT_SECRET` | 机器人 AppSecret | 空 |
| `QQ_BOT_INTENTS` | 事件订阅位掩码（1<<25 = 群@+单聊） | `33554432` |

> 官方网关为**出站 WebSocket**，只需本机出网，**无需公网 IP**。群消息需 `@机器人` 才会触发；
> 回复超长会截断（v2 单条有长度限制，后续可加分片）。

## 十、目录结构

```
enterprise-agent/
├── .env / .env.example      # 配置（密钥留空待填）
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── src/
│   ├── config.py            # pydantic-settings 读 .env
│   ├── agent/
│   │   ├── llm.py           # SiliconFlow 对话 / 嵌入封装
│   │   ├── rag.py           # 分块 + 批量嵌入 + Chroma 检索
│   │   ├── tools.py         # 工具注册与实现（HR/IT）
│   │   ├── router.py        # 意图分类 + 简单直答
│   │   ├── agent.py           # 主 Agent 异步循环 arun()（RAG + 工具 + SSE，不阻塞事件循环）
│   │   ├── prompts.py       # 提示词
│   │   └── mock_db.py       # Mock 企业后端（留真实接口位）
│   ├── qqbot/               # QQ 机器人接入（官方平台 WSS 网关）
│   │   └── client.py        # 鉴权 + 网关事件循环 + 转发 Agent + 回包
│   ├── api/main.py          # FastAPI 接口 + 托管前端
│   └── data/{docs,chroma,mock}
├── web/                     # React + Vite + Tailwind 前端
├── scripts/                 # ingest.py / smoke.py / connect_qqbot.py / 验证脚本
└── tests/                   # pytest 用例
```

---

## 十一、版权与免责声明

- **禁止商用**：本项目（含全部源代码、文档与示例知识库）仅供个人学习、研究与技术演示之用，**严禁任何商业用途**（包括但不限于售卖、二次打包发布、接入商业产品、用于营利性服务）。如需商用，请先获得作者书面授权。
- **「原样」提供**：代码与文档按「现状」提供，不附带任何明示或暗示的担保（包括但不限于适用性、无侵权、无缺陷、特定用途适用性）。作者不对使用本项目产生的任何直接或间接损失负责。
- **使用风险自担**：运行本项目需接入第三方服务（硅基流动 SiliconFlow、QQ 机器人开放平台等），请自行遵守其服务条款、速率限制与合规要求；由此产生的费用、封禁或纠纷由使用者自行承担。
- **数据与隐私**：本项目不收集、不上传任何用户数据；会话历史与向量库仅存储于本地。使用者有义务确保所处理数据符合所在地区法律法规（如《个人信息保护法》《生成式人工智能服务管理暂行办法》等）。
- **内容免责**：示例知识库（`src/data/docs/*.md`）与 Mock 后端均为演示数据，不代表任何真实企业的制度或政策，请勿直接用于生产决策。
- **第三方权益**：文中涉及的模型、平台、商标与品牌归各自所有者所有，本项目与任何第三方无隶属或代言关系。
- **合规提示**：若用于对外提供服务，请自行完成生成式 AI 服务备案 / 算法备案等合规手续。
