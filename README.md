# 网文转漫剧剧本 · 多智能体工作流

基于 **LangGraph** 框架实现的生产级多智能体系统，将网络小说自动改编为包含台词、分镜、音效的完整漫剧剧本。

---

## � 网页可视化界面 (Web UI)

本项目提供了一个基于 Gradio 的开箱即用可视化操作面板。

### 启动服务

```bash
# 激活环境并启动服务
./run.sh
```

### 访问面板

您可以直接访问目前已经启动在云端的服务地址：
- 🌐 **[http://43.159.142.206:7860](http://43.159.142.206:7860)**

> *如果您在自己的机器或新服务器上部署，使用浏览器访问对应机器的 `http://<您的IP>:7860`（记得在云服务后台/安全组中放行 7860 端口的 TCP 入站规则）*

在 Web 界面中您将能够直接可视化地配置模型、粘帖文本或上传 txt 文件、修改分片设定以及实时查看整个多智能体的协作工作流进度。

---

## �🎭 系统架构

```
网文输入
  │
  ▼
✍️ 编剧 Agent          → 提炼对白、独白、旁白（结构化 JSON）
  │
  ▼ 
🖼️ 分镜师 Agent        → 生成 AI 绘画 Prompt（4维度：主体/环境/光影/镜头）
  │
  ▼
🎵 音效师 Agent        → 设计三层声音（环境音/动作音效/BGM）
  │
  ▼
🎬 导演 Agent          → 四维审核（忠实度/情绪张力/视觉丰满度/声音清晰度）
  │
  ├──── ✅ APPROVE → 最终剧本输出
  │
  └──── 🔄 REVISE → 退回指定 Agent 重做（最多 MAX_REVISIONS 轮）
```

### 智能体分工

| Agent | 核心职责 | 输出格式 |
|---|---|---|
| ✍️ 编剧 | 提炼剧情，改写旁白，处理设定段落 | JSON 场景列表 |
| 🖼️ 分镜师 | 转化画面，生成绘画 Prompt，规划运镜 | JSON 分镜列表 |
| 🎵 音效师 | 设计环境音/动作音效/BGM 三层声音 | JSON 音效列表 |
| 🎬 导演 | 四维审核，指定退回目标，撰写修改意见 | JSON 决策对象 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd /Users/liujie50/workspace/multi_agent
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 使用 OpenAI（默认）
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-your-key-here
export LLM_MODEL=gpt-4o

# 或使用 Gemini
export LLM_PROVIDER=gemini
export GOOGLE_API_KEY=your-google-key
export LLM_MODEL=gemini-2.5-flash

# 或使用 Ollama（本地，无需 Key）
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1
```

### 3. 运行

```bash
# 使用内置示例网文（仙侠类型）
python main.py

# 指定你自己的网文文件
python main.py --input path/to/your_novel.txt --type 仙侠/玄幻

# 查看所有选项
python main.py --help
```

### 4. 查看输出

运行完成后，在 `./output/` 目录中会生成两个文件：
- `final_script_<时间戳>.txt`：面向制作团队的完整漫剧剧本（人类可读）
- `raw_data_<时间戳>.json`：所有 Agent 的原始输出数据（供二次处理）

---

## 📁 项目结构

```
multi_agent/
├── main.py                  # 入口，命令行参数处理
├── state.py                 # LangGraph 共享状态（TypedDict）
├── graph.py                 # LangGraph 图定义（节点+边+路由）
├── config.py                # 全局配置（LLM、最大迭代次数等）
├── requirements.txt
├── agents/
│   ├── llm_factory.py       # LLM 工厂（支持 OpenAI/Gemini/Ollama）
│   ├── screenwriter.py      # 编剧 Agent
│   ├── storyboard.py        # 分镜师 Agent
│   ├── sound_designer.py    # 音效师 Agent
│   └── director.py          # 导演 Agent（含审核+最终剧本格式化）
├── prompts/
│   ├── screenwriter_prompt.md   # 编剧工作守则（5条核心规则）
│   ├── storyboard_prompt.md     # 分镜师工作守则
│   ├── sound_designer_prompt.md # 音效师工作守则
│   └── director_prompt.md       # 导演审核标准（4维度）
├── sample_input/
│   └── chapter_1.txt        # 示例网文（仙侠类型）
└── output/                  # 生成的剧本输出目录
```

---

## ⚙️ 高级配置

### 环境变量

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `openai` | LLM 后端：`openai` / `gemini` / `ollama` |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `OPENAI_API_KEY` | `` | OpenAI API Key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 支持中转代理 |
| `GOOGLE_API_KEY` | `` | Google API Key |
| `MAX_REVISIONS` | `3` | 导演最多打回几轮 |
| `DEBUG` | `false` | 设为 `true` 查看每步原始输出 |

### 支持的小说类型

- 仙侠/玄幻
- 都市/现代
- 赛博朋克/科幻
- 古代言情
- 武侠
- 末世/灾难
- 校园/青春
- 历史

---

## 🧠 核心设计决策

> 以下设计决策来自与 Gemini 的深度讨论（2026.02）

### 为什么选择 LangGraph？
LangGraph 将工作流建模为**有向图**，天然支持"条件边"，完美实现了导演的"打回重做"循环。相比 CrewAI 更适合需要精细控制循环逻辑的场景。

### 导演退回优先级
当多个 Agent 都需要修改时，优先退回**最上游**的 Agent：
`编剧 > 分镜师 > 音效师`

这是因为编剧是基础，修改编剧后，下游的分镜和音效会随新剧本自动重跑。

### 无限循环保护
通过 `MAX_REVISIONS` 环境变量限制最大审核轮数。超出后强制通过，避免 API 费用失控。

### 纯设定段落处理
网文中大量的世界观介绍、功法说明等段落，按以下规则处理：
1. 提炼为 ≤3句旁白（VO）
2. 在 `visual_hint` 字段存储配图建议供分镜师参考

---

## 🔮 未来计划

- [ ] 接入 Midjourney/SD API 直接生成分镜图片
- [ ] 添加角色一致性管理（确保同一角色在所有场景外观一致）
- [ ] 支持长文本拆分（自动将长章节分批处理）
- [x] Web UI 界面（上传文件 → 实时查看进度 → 下载剧本）
- [ ] 导出为专业剧本格式（Final Draft / PDF）
