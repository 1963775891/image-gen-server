# 描述：基于即梦AI的图片生成云服务，专为云端部署和客户端集成设计。
# 默认使用即梦3.0模型，并支持图生图、模型选择等功能。
# 作者：凌封 (微信fengin)，由AI助手修改和增强
# GITHUB: https://github.com/fengin/image-gen-server.git
# 相关知识可以看AI全书：https://aibook.ren

import os
import re
import logging
from sys import stdin, stdout
from fastmcp import FastMCP
import mcp.types as types

# 仅从proxy.jimeng模块导入图片生成器
from proxy.jimeng.images import generate_images

# ######################################################################
# 请在这里填入你自己的配置
# ######################################################################
# 用于图片生成的即梦 session_id
JIMENG_API_TOKEN = "057f7addf85dxxxxxxxxxxxxx" # 你登录即梦获得的session_id，支持多个，在后面用逗号分隔 
# ######################################################################


stdin.reconfigure(encoding='utf-8')
stdout.reconfigure(encoding='utf-8')

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建FastMCP实例
mcp = FastMCP("image-gen-cloud-server")

@mcp.tool("use_description")
async def list_tools():
    """列出所有可用的工具及其参数"""
    return {
        "tools": [
            {
                "name": "generate_image",
                "description": "根据文本描述或参考图生成静态图片。默认使用即梦3.0模型。可以直接在prompt中通过说'用即梦2.0'等来指定模型。返回Markdown格式的图片。",
                "parameters": {
                    "prompt": { "type": "string", "description": "图片的文本描述。可以在描述中包含模型名称，如'用即梦2.0pro画一只猫'。", "required": True },
                    "file_path": { "type": "string", "description": "【图生图】参考图片的本地路径或网络URL(可选)。", "required": False },
                    "model": { "type": "string", "description": "精确选择图片模型(可选, 默认 'jimeng-3.0')。", "required": False },
                }
            }
        ]
    }

def find_model_in_prompt(prompt_text: str) -> str:
    """从prompt中智能查找图片模型关键字"""
    model_keywords = {
        r'即梦3.0|jimeng-3.0|jimeng 3.0': 'jimeng-3.0',
        r'即梦2.1|jimeng-2.1|jimeng 2.1': 'jimeng-2.1',
        r'即梦2.0pro|即梦2.0 pro|jimeng-2.0-pro|jimeng 2.0-pro|jimeng 2.0 pro': 'jimeng-2.0-pro',
        r'即梦2.0|jimeng-2.0|jimeng 2.0': 'jimeng-2.0',
        r'即梦1.4|jimeng-1.4|jimeng 1.4': 'jimeng-1.4',
        r'即梦xlpro|即梦xl pro|jimeng-xl-pro|jimeng xl-pro|jimeng xl pro': 'jimeng-xl-pro'
    }
    prompt_lower = prompt_text.lower()
    for pattern, model_name in model_keywords.items():
        if re.search(pattern, prompt_lower):
            logger.info(f"在prompt中检测到图片模型，选用: {model_name}")
            return model_name
    return None

@mcp.tool("generate_image")
async def generate_image_tool(
    prompt: str,
    file_path: str = None,
    # 将此处的默认值改为 "jimeng-3.0"
    model: str = "jimeng-3.0"
) -> list[types.TextContent]:
    
    logger.info(f"收到图片生成请求: prompt='{prompt}', file_path='{file_path}', model_param='{model}'")
    
    # 智能模型选择逻辑保持不变
    final_model = find_model_in_prompt(prompt) or model
    
    if not prompt: return [types.TextContent(text="**错误**: prompt不能为空")]

    try:
        # 调用核心生成函数
        image_urls = generate_images(
            prompt=prompt,
            refresh_token=JIMENG_API_TOKEN,
            model=final_model,
            file_path=file_path
        )
        if not image_urls:
             return [types.TextContent(text="**错误**: API未能返回任何图片URL。")]
        
        # 格式化为Markdown并返回
        markdown_output = "\n\n".join([f"![Generated Image]({url})" for url in image_urls])
        logger.info(f"成功生成 {len(image_urls)} 张图片, 返回Markdown。")
        return [types.TextContent(text=markdown_output)]
        
    except Exception as e:
        error_msg = f"**图片生成过程中发生错误**: {str(e)}"
        logger.exception(error_msg)
        return [types.TextContent(text=error_msg)]

if __name__ == "__main__":
    if "在这里填入" in JIMENG_API_TOKEN:
        logger.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.error("!!! 错误：请先在 server.py 文件中设置您的 JIMENG_API_TOKEN !!!")
        logger.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        logger.info("启动即梦图片生成云服务（默认模型: 即梦3.0）...")
        mcp.run()
