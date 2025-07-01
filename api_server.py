# 描述: 兼容 Dify 和 LobeChat 的即梦图片生成API服务 (带尺寸选择功能)。
# 作者: AI助手根据用户需求整合和创建

import uvicorn
import json
import re
import logging
from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

# 导入我们强大的图片生成模块
from proxy.jimeng.images import generate_images

# --- FastAPI 应用设置 ---
app = FastAPI(
    title="即梦图片生成通用API(带比例)",
    description="一个为 Dify 和 LobeChat 设计的，支持尺寸选择的即梦图片生成插件服务。",
    version="1.1.0-Final-Ratio"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- 请求体模型定义 (新增 aspect_ratio) ---
class ImageRequest(BaseModel):
    prompt: str = Field(..., description="图片的文本描述。")
    aspect_ratio: Optional[str] = Field("1:1", description="图片比例, 如 1:1, 16:9")
    file_path: Optional[str] = Field(None, description="【图生图】参考图片的网络URL。")
    model: Optional[str] = Field("jimeng-3.0", description="精确选择图片模型(可选, 默认 'jimeng-3.0')。")


# --- 新增：宽高比与像素尺寸的映射字典 ---
ASPECT_RATIO_MAP = {
    "1:1": (1024, 1024),
    "16:9": (1664, 936),
    "9:16": (936, 1664),
    "4:3": (1472, 1104),
    "3:4": (1104, 1472),
    "3:2": (1584, 1056),
    "2:3": (1056, 1584),
    "21:9": (2016, 864),
}

# (find_model_in_prompt 和 get_manifest 函数保持不变, 此处省略)
def find_model_in_prompt(prompt_text: str) -> str:
    # ... (代码同上一版) ...
    model_keywords = {
        r'即梦3.0|jimeng-3.0|jimeng 3.0': 'jimeng-3.0', r'即梦2.1|jimeng-2.1|jimeng 2.1': 'jimeng-2.1',
        r'即梦2.0pro|即梦2.0 pro|jimeng-2.0-pro': 'jimeng-2.0-pro', r'即梦2.0|jimeng-2.0|jimeng 2.0': 'jimeng-2.0',
        r'即梦1.4|jimeng-1.4|jimeng 1.4': 'jimeng-1.4', r'即梦xlpro|即梦xl pro|jimeng-xl-pro': 'jimeng-xl-pro'
    }
    prompt_lower = prompt_text.lower()
    for pattern, model_name in model_keywords.items():
        if re.search(pattern, prompt_lower):
            logging.info(f"在prompt中检测到图片模型，选用: {model_name}")
            return model_name
    return None

@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    try:
        with open('manifest.json', 'r', encoding='utf-8') as f:
            return JSONResponse(content=json.load(f))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="manifest.json not found")


# --- API端点：核心图片生成功能 (已更新) ---
@app.post("/generate_image_api")
async def create_image_endpoint(
    request_body: ImageRequest,
    x_lobe_plugin_settings: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    # 1. 解析Token (逻辑不变)
    token = None
    if x_lobe_plugin_settings:
        try: token = json.loads(x_lobe_plugin_settings).get("session_id")
        except: pass
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    if not token:
        raise HTTPException(status_code=401, detail="无效或缺失的认证Token。")

    # 2. 解析模型 (逻辑不变)
    final_model = find_model_in_prompt(request_body.prompt) or request_body.model
    
    # 3. 新增：解析宽高比，获取像素尺寸
    selected_ratio = request_body.aspect_ratio if request_body.aspect_ratio in ASPECT_RATIO_MAP else "1:1"
    width, height = ASPECT_RATIO_MAP[selected_ratio]

    logging.info(f"API收到请求: prompt='{request_body.prompt}', model='{final_model}', ratio='{selected_ratio}', size='{width}x{height}'")

    # 4. 调用核心服务 (传入新的width和height)
    try:
        image_urls = generate_images(
            prompt=request_body.prompt,
            refresh_token=token,
            model=final_model,
            file_path=request_body.file_path,
            width=width,
            height=height
        )
        if not image_urls:
            return Response(content="**错误**: API未能返回任何图片URL。", media_type="text/plain")
        
        # 5. 格式化并返回 (逻辑不变)
        markdown_output = "\n\n".join([f"![image]({url})" for url in image_urls])
        return Response(content=markdown_output, media_type="text/plain")

    except Exception as e:
        logging.exception(f"图片生成过程中发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

# --- 启动命令 ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)