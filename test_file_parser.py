import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY")),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

def analyze_pdf_and_save(pdf_path: str):
    """
    分析指定的 PDF 文件并将结果保存为同名的 md 文件
    
    Args:
        pdf_path (str): PDF 文件的路径
    """
    file_path = Path(pdf_path)
    
    if not file_path.exists():
        print(f"❌ 错误: 文件不存在 - {file_path}")
        return

    # 确定输出 md 文件的路径
    output_md_path = file_path.with_suffix('.md')

    print(f"正在上传文件: {file_path}")
    try:
        # 步骤 1: 上传文件
        file_object = client.files.create(
            file=file_path, 
            purpose="file-extract"
        )
        
        print(f"✅ 文件上传成功！")
        print(f"   文件ID: {file_object.id}")
        print(f"   文件名: {file_object.filename}")
        print(f"   文件大小: {file_object.bytes} bytes\n")
        
        # 步骤 2: 使用 qwen-long 模型进行分析
        print("正在调用 AI 分析 PDF 文件...")
        completion = client.chat.completions.create(
            model="qwen-long",  # 必须使用 qwen-long 模型
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},  # sys1: 角色定义
                {'role': 'system', 'content': f'fileid://{file_object.id}'},  # sys2: 文档内容
                {
                    'role': 'user', 
                    'content': '你是一个专业的论文分析助手，请对文章进行完整分析：1. 说明其提出的具体技术方法与实现路径；2. 归纳主要结论与创新点；3. 必要时补充方法的可行性与局限性概述。'
                }
            ],
            stream=True,
            stream_options={"include_usage": True}
        )
        
        print("\n" + "="*80)
        print("AI 分析结果：")
        print("="*80 + "\n")
        
        full_content = ""
        for chunk in completion:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_content += content
                print(content, end='', flush=True)
            
            if chunk.usage:
                print(f"\n\n总计 tokens: {chunk.usage.total_tokens}")
        
        # 步骤 3: 保存结果为 md 文件
        with open(output_md_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
        
        print(f"\n\n✅ 分析结果已保存至: {output_md_path}")

    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 示例用法
    target_pdf = "data/pdfs/2017_Attention Is All You Need.pdf"
    analyze_pdf_and_save(target_pdf)
