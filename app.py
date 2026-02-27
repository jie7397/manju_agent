import gradio as gr
import os
import tempfile
from pathlib import Path

# Fix python path just in case
import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import SUPPORTED_NOVEL_TYPES, MAX_REVISIONS
from main import run_single_chunk, merge_chunk_results
from utils.chunker import split_into_chunks, get_chunk_info

import config

def generate_script(text_input, file_input, novel_type, llm_provider, llm_model, api_key, chunk_size, chunk_overlap):
    if not text_input and not file_input:
        yield "请提供文本或上传txt文件"
        return
    
    novel_text = ""
    if text_input:
        novel_text += text_input + "\n"
        
    if file_input:
        try:
            # Gradio file objects usually have a 'name' attribute or it's a temp path
            file_path = file_input if isinstance(file_input, str) else file_input.name
            with open(file_path, 'r', encoding='utf-8') as f:
                novel_text += f.read()
        except Exception as e:
            yield f"读取文件失败: {e}"
            return

    novel_text = novel_text.strip()
    if not novel_text:
        yield "文本内容为空！"
        return

    # Setup environment variables dynamically
    config.LLM_PROVIDER = llm_provider
    os.environ["LLM_PROVIDER"] = llm_provider

    if llm_provider == "openai":
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            config.OPENAI_API_KEY = api_key
    elif llm_provider == "gemini":
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            config.GOOGLE_API_KEY = api_key            
    
    if llm_model:
        os.environ["LLM_MODEL"] = llm_model
        config.LLM_MODEL = llm_model
        
    # Optional: we can disable HUMAN_REVIEW to ensure it doesn't block
    config.HUMAN_REVIEW = False

    info = get_chunk_info(novel_text, chunk_size)
    chunks = split_into_chunks(novel_text, chunk_size, chunk_overlap)
    
    chunk_states = []
    scene_offset = 0
    yield f"🚀 开始处理，共分为 {len(chunks)} 段 (总字数: {info['total_chars']})...\n"
    
    output_log = f"🚀 开始处理，共分为 {len(chunks)} 段 (总字数: {info['total_chars']})...\n\n"
    
    try:
        for i, chunk in enumerate(chunks):
            log_msg = f"⏳ 正在处理第 {i + 1}/{len(chunks)} 段 (字数: {len(chunk)}, 从偏移量 {scene_offset + 1} 开始)...\n"
            output_log += log_msg
            yield output_log
            
            # 运行工作流
            state = run_single_chunk(chunk, novel_type, scene_offset)
            chunk_states.append(state)
            
            scene_count = len(state.get("screenplay_scenes", []))
            scene_offset += scene_count
            
            log_msg = f"✅ 第 {i + 1} 段处理完成，本段场景数: {scene_count}，累积场景数: {scene_offset}\n\n"
            output_log += log_msg
            yield output_log
            
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        yield output_log + f"\n❌ 处理出错:\n{err}"
        return

    if len(chunk_states) == 1:
        final_state = chunk_states[0]
    else:
        log_msg = f"🔗 正在合并 {len(chunks)} 段结果...\n"
        output_log += log_msg
        yield output_log
        final_state = merge_chunk_results(chunk_states, novel_type)
        
    log_msg = f"\n🎉 生成完成！\n"
    output_log += log_msg
    yield output_log
    
    final_script = final_state.get("final_script", "（无最终剧本输出）")
    yield final_script


# Custom Theme Config
custom_theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="purple",
    neutral_hue="slate",
    spacing_size="lg",
    radius_size="lg",
    font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"]
).set(
    body_background_fill="*neutral_50",
    body_text_color="*neutral_900",
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
    border_color_primary="*primary_200",
)

with gr.Blocks(title="漫剧智能剧本生成") as demo:
    
    gr.HTML('''
        <div style="padding: 10px 0;">
            <div class="title-text">漫剧智能剧本生成引擎</div>
            <div class="subtitle-text">将小说原著文本转化为结构化的漫剧分镜剧本流程引擎</div>
        </div>
    ''')
    
    with gr.Row():
        with gr.Column(scale=9, elem_classes="block-container"):
            gr.Markdown("### 📝 第一步：输入文稿", elem_classes="markdown-header")
            with gr.Tabs():
                with gr.TabItem("📋 直接粘贴"):
                    text_input = gr.Textbox(
                        lines=10, 
                        label="小说原文（引擎将会读取进行解析）", 
                        placeholder="在此粘贴小说内容...\n支持超长文本，系统会自动在后台分段并合并处理。"
                    )
                with gr.TabItem("📂 附件上传"):
                    file_input = gr.File(
                        label="上传 txt 文件", 
                        file_types=[".txt"],
                        height=200
                    )
                    
            with gr.Row():
                submit_btn = gr.Button("🚀 启动引擎开始生成", variant="primary", size="lg")
                
        with gr.Column(scale=4, elem_classes="block-container"):
            gr.Markdown("### ⚙️ 第二步：参数配置", elem_classes="markdown-header")
            
            with gr.Group():
                novel_type = gr.Dropdown(choices=SUPPORTED_NOVEL_TYPES, value="仙侠/玄幻", label="🎭 小说题材")
                llm_provider = gr.Dropdown(choices=["openai", "gemini"], value="openai", label="🤖 大语言模型源")
                llm_model = gr.Textbox(value="gpt-4o", label="🧮 模型名称 (e.g. gpt-4o, gemini-2.5-flash)")
                api_key = gr.Textbox(value="", label="🔑 API Key (如已配环境变量则留空)", type="password")
            
            with gr.Accordion("🛠️ 进阶分片控制", open=False):
                gr.Markdown("为防止超出 Tokens 限制，长文会自动开启切片工作流：")
                chunk_size = gr.Slider(minimum=500, maximum=10000, value=2000, step=100, label="单位切片字符数 (Chunk Size)")
                chunk_overlap = gr.Slider(minimum=0, maximum=1000, value=200, step=50, label="保留上下文字符数 (Chunk Overlap)")
                
    with gr.Row():
        with gr.Column(scale=1, elem_classes="block-container"):
            gr.Markdown("### 🎯 生成面板", elem_classes="markdown-header")
            output_text = gr.Textbox(
                lines=25, 
                label="实时工作流日志 & 最终剧本产物"
            )

    submit_btn.click(
        fn=generate_script,
        inputs=[text_input, file_input, novel_type, llm_provider, llm_model, api_key, chunk_size, chunk_overlap],
        outputs=output_text
    )

if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0", 
        show_error=True,
        theme=custom_theme,
        css="""
        .title-text { text-align: center; font-size: 2.2em; font-weight: 700; color: #1e1e1e; margin-bottom: 0px !important; }
        .subtitle-text { text-align: center; color: #555555; font-size: 1.1em; margin-top: 5px !important; margin-bottom: 25px !important; }
        .block-container { box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1); border-radius: 10px; background-color: white; padding: 15px; margin-bottom: 20px; }
        .markdown-header { margin-bottom: 15px !important; }
        """
    )


