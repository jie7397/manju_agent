# Web Service Architecture for Multi-Agent Script Generator

这个文档详细设计了如何将现有的 LangGraph 多智能体脚本生成器包装成一个提供 Web API 的服务。用户可以上传 `.txt` 文件，然后获取对应的格式化剧本文件或 JSON 数据。

## 1. 技术栈选择

* **Web 框架：FastAPI**
    * 选择原因：Python 圈内最快、最好用的异步框架。自带 Swagger 文档，非常适合这种 API 优先的服务。
* **任务队列：Celery + Redis / ARQ + Redis**
    * 选择原因：多智能体工作流非常耗时（可能长达数分钟），如果在 HTTP 请求里同步等待会导致超时或阻塞服务器。必须使用异步任务队列。考虑到 FastAPI 的异步特性，推荐使用更轻量级的 `arq` (异步 Redis 队列)，或者老牌的 `Celery`。
* **对象存储 (可选)：MinIO / AWS S3**
    * 选择原因：如果用户上传的 txt 以及生成的输出文件很多，本地磁盘管理起来比较困难，可以使用临时或持久化的对象存储。本设计中为了简化，使用本地目录 `/tmp` 或指定目录。这个是生产环境可以考虑的。
* **LLM 调用**：直接复用现有的 LangChain + LangGraph。

## 2. 核心架构设计

这是一个经典的异步任务架构：

```mermaid
graph TD
    A[User/FrontEnd] -->|1. Upload File + Config| B(FastAPI Server)
    B -->|2. Save File & Create Task ID| C{Database/Redis Key}
    B -->|3. Publish Task| D[Redis Queue]
    B -.->|4. Return Task ID| A
    
    D --> E[Worker Process]
    E -->|Load File| F{File System / Storage}
    E -->|Run| G((LangGraph Workflow))
    G -->|Update Status/Progress| C
    G -->|Generate Results| F
    E -->|Final Status| C

    A -->|5. Poll Task Status| B
    B -->|Read| C
    B -.->|6. Return Status (running/done...) | A

    A -->|7. Download Script| B
    B -->|Fetch| F
    B -.->|Return File| A
```

## 3. 详细流程设计

### 3.1 用户提交任务阶段 (Upload Phase)

1. **接口定义**: `POST /api/v1/generate`
2. **输入负载 (Payload)**:
    * `file`: (Multipart Form) 用户上传的 `.txt` 小说文件。
    * `novel_type`: (String) 小说类型（例如：仙侠/玄幻，都市/现代等）。
    * `chunk_size`: (Integer, 可选) 默认 2000。
    * 也可以提供其他可选参数，比如 `max_revisions`，但基础版可以先写死在服务端。
3. **处理逻辑**:
    * 接收到文件后，FastAPI 生成一个全局唯一的 `task_id` (使用 UUID4)。
    * 将上传的文件保存到服务器的指定存储目录中（例如 `uploads/{task_id}/input.txt`）。
    * 将任务的初始状态（如：`{"status": "pending", "novel_type": "仙侠/玄幻"}`）写入 Redis。
    * 将带有 `task_id` 和任务详情的消息发布到 Redis 的任务队列中。
4. **输出**: 立即返回 `task_id`，告诉用户任务已受理。
    * `{"task_id": "123e4567-e89b-12d3...", "status": "pending", "message": "Task created successfully."}`

### 3.2 任务处理阶段 (Worker Phase)

这个阶段在后台的 Worker 进程中运行（与 FastAPI 主进程分离），可以使用 `celery worker` 或者自定义的 Python 后台循环。

1. **获取任务**: Worker 监听 Redis 队列，一旦有新任务就取走。
2. **更新状态**: Worker 开始处理时，更新 Redis 中的状态为 `{"status": "running", "progress": "提取角色"}`。
3. **执行核心逻辑**:
    * 读取 `uploads/{task_id}/input.txt` 文件内容。
    * 调用现有的多智能体流水线：
      ```python
      from graph import get_workflow
      from main import build_initial_state, merge_chunk_results, run_single_chunk
      # ... 使用工具链对加载的内容执行分析 ...
      ```
    * 每次完成一个智能体的步骤（或者每一个 chunk 完成），可以更新一下 Redis 中的进度：`{"status": "running", "progress": "编剧完成，正在分镜"}`。
4. **生成与保存**:
    * 运行结束后，将生成的带有结果信息的 `final_script` 和 `raw_data.json` 保存在特定文件夹：`outputs/{task_id}/final_script.txt` 和 `outputs/{task_id}/raw_data.json`。
5. **结束标记**:
    * 更新 Redis 中的任务状态为完成：`{"status": "completed", "result_path": " outputs/{task_id}/final_script.txt"}`。
    * 如果中间抛出异常，更新状态为 `{"status": "failed", "error": "LLM Provider Timeout"}`。

### 3.3 状态追踪阶段 (Polling/Webhook Phase)

在任务执行的过程中，前端通常轮询后端获取状态。

1. **接口定义**: `GET /api/v1/tasks/{task_id}/status`
2. **处理逻辑**: FastAPI 接收到请求后，根据 `task_id` 去 Redis 查询对应的状态记录并返回。
3. **输出示例**:
    * `{ "task_id": "...", "status": "running", "progress": "Scene 2 / Storyboard Agent" }`
    * `{ "task_id": "...", "status": "completed", "download_url": "/api/v1/tasks/123/download/script" }`

*(注：如果需要更实时的交互，也可以选用 WebSocket，由后端实时向前端推送 Agent 输出的过程)*

### 3.4 下载与结果获取阶段

1. **接口定义**:
    * 获取 TXT: `GET /api/v1/tasks/{task_id}/download/script`
    * 获取 JSON: `GET /api/v1/tasks/{task_id}/download/json`
2. **处理逻辑**: 根据 `task_id` 找到对应的文件位置，使用 FastAPI 的 `FileResponse` 返回文件，设置正确的 MIME 类型和下载头。

## 4. 需要进行的改造准备

将现有的终端 Python 脚本改造成这种 Web 服务，需要做一些解耦：

### 4.1 核心流程剥离
目前 `main.py` 里面的各种 `print` 在 Web 环境下是看不到的。需要抽取出一个纯净的执行函数：
```python
# services/workflow_runner.py
def run_script_generation(file_content: str, novel_type: str, progress_callback=None):
    """
    负责接收文本并返回生成的 JSON 字典（或者文件路径）。
    可以在执行流程的特定地方调用 progress_callback(status_string)。
    """
    # 里面包含拆分 chunk -> build_initial_state -> ...
```

### 4.2 配置管理调整
原先从环境变量、`config.py` 读取的内容可能需要调整。Web 后端需要确保能够接受并发。LangGraph 依赖的 LangChain LLM Client 默认支持并发，但需要注意并发调用时的限流（Rate Limit）问题，可能要做全局并发限制。

### 4.3 状态跟踪（最棘手的部分）
我们原先有一个很棒的 `Progress` rich 输出类。我们要增加一个新的机制。一种是回调函数，像这样注入到 `WorkflowProgress`：
```python
# 修改 utils/progress.py
class WorkflowProgress:
    def __init__(self, update_callback=None):
        self.update_callback = update_callback
        ...

    def done(self, agent_id: str, result_summary: str = ""):
        # 原有的 print
        ...
        if self.update_callback:
            self.update_callback({"agent": agent_id, "status": "done", "summary": result_summary})
```

## 5. 项目结构示例 (如果是 FastAPI)

```
multi_agent/
├── web/                   <-- 新增 Web 服务目录
│   ├── app.py             <-- FastAPI 启动与路由配置
│   ├── worker.py          <-- 监听队列执行后台任务的代码
│   ├── dependencies.py
│   ├── uploads/           <-- 用户上传文件的暂存位置
│   └── outputs/           <-- 结果输出的目录
├── agents/             
├── utils/              
├── config.py           
├── graph.py            
├── state.py            
├── main.py                <-- 依然可用的 CLI 工具
└── requirements.txt
```

## 6. 一段 FastAPI + 后台任务的概念验证代码 (简易实现)

如果你不需要那么复杂的 Redis 队列，FastAPI 自己提供了一个简单的 `BackgroundTasks`，但这对于消耗几十秒的任务不太理想，如果服务器重启任务会丢，但适合初期 MVP：

```python
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
import uuid
import os
from pydantic import BaseModel

app = FastAPI()

# 简单的内存模拟数据库
task_db = {} 

def process_novel_task(task_id: str, file_path: str, novel_type: str):
    task_db[task_id]["status"] = "running"
    
    try:
        # 1. 读取文件
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        # 2. 调用修改后的核心方法
        # final_state = run_script_generation(text, novel_type, progress_callback=lambda p: update_progress(task_id, p))
        
        # 3. 保存文件并打上标记 (使用伪代码替代)
        out_path = f"outputs/{task_id}_script.txt"
        with open(out_path, "w", encoding="utf-8") as out:
            out.write("fake result")
            
        task_db[task_id]["status"] = "completed"
        task_db[task_id]["result"] = out_path
        
    except Exception as e:
        task_db[task_id]["status"] = "failed"
        task_db[task_id]["error"] = str(e)


@app.post("/api/v1/generate")
async def generate_script(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    novel_type: str = Form(...)
):
    task_id = str(uuid.uuid4())
    
    # 保存上传的文件
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{task_id}.txt"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # 记录状态
    task_db[task_id] = {"status": "pending", "novel_type": novel_type}

    # 提交后台任务
    background_tasks.add_task(process_novel_task, task_id, file_path, novel_type)

    return {"task_id": task_id, "status": "pending"}


@app.get("/api/v1/tasks/{task_id}")
def get_task_status(task_id: str):
    if task_id not in task_db:
        return {"error": "Task not found"}
    return task_db[task_id]
```

## 7. 总结

要从 CLI 脚本转移到 Web 服务，由于生成时间长，你绝对需要引入**异步架构思想（排队系统）**。你必须把现有的命令式输出变成事件式输出（回调或写入某些数据库）。如果你想要构建这样一个服务，你需要决定是用轻量级的 `FastAPI 背景任务`，还是去搭建一个完整的 `Redis + Celery` 系统。
