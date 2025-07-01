# 描述: 即梦图片生成API服务 (Dify & LobeChat 统一最终版)

import uvicorn
import json
import logging
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from typing import Optional, Dict, Tuple

from proxy.jimeng.images import generate_images

app = FastAPI(
    title="即梦图片生成统一API",
    version="Unified-Final-Perfect"
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class ImageRequest(BaseModel):
    prompt: str
    model: Optional[str] = "jimeng-3.0"
    aspect_ratio: Optional[str] = "1:1"

RATIO_MAP: Dict[str, Dict[str, Tuple[int, int]]] = {
    "jimeng-3.0": {
        "1:1": (1328, 1328), "16:9": (1664, 936), "9:16": (936, 1664), "4:3": (1472, 1104),
        "3:4": (1104, 1472), "3:2": (1584, 1056), "2:3": (1056, 1584), "21:9": (2016, 864),
    },
    "old_models": {
        "1:1": (1360, 1360), "16:9": (1360, 765), "9:16": (765, 1360), "4:3": (1360, 1020),
        "3:4": (1020, 1360), "3:2": (1360, 906), "2:3": (906, 1360), "21:9": (1358, 582),
    }
}
auth_scheme = HTTPBearer()

def get_image_dimensions(model: str, ratio: str) -> Tuple[int, int]:
    model_group = "jimeng-3.0" if model == "jimeng-3.0" else "old_models"
    ratios = RATIO_MAP.get(model_group, RATIO_MAP["old_models"])
    return ratios.get(ratio, ratios["1:1"])

# --- 为 Dify 提供服务 ---
@app.get("/openapi.json", include_in_schema=False)
async def get_openapi_spec():
    return FileResponse('openapi.json')

@app.post("/generate_image_for_dify")
async def generate_image_for_dify(
    req_body: ImageRequest,
    token: HTTPAuthorizationCredentials = Depends(auth_scheme)
):
    width, height = get_image_dimensions(req_body.model, req_body.aspect_ratio)
    logging.info(f"Dify工具收到请求: prompt='{req_body.prompt}', model='{req_body.model}', size='{width}x{height}'")
    try:
        image_urls = generate_images(prompt=req_body.prompt, refresh_token=token.credentials, model=req_body.model, width=width, height=height)
        return JSONResponse(content={"image_urls": image_urls})
    except Exception as e:
        logging.error(f"Dify请求处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 为 LobeChat 提供服务 ---
@app.get("/manifest.json", include_in_schema=False)
async def get_lobe_manifest():
    return FileResponse('manifest.json')

@app.post("/generate_image_for_lobe")
async def generate_image_for_lobe(
    request: Request,
    x_lobe_plugin_settings: Optional[str] = Header(None)
):
    try:
        # --- 终极BUG修复：正确处理LobeChat的请求体 ---
        body_json = await request.json()
        # LobeChat的逻辑是，它会把所有参数打包成一个叫'arguments'的JSON字符串
        # 但如果用户没有在UI上修改任何参数，它发来的body里可能就没有'arguments'
        # 所以我们需要做一个兼容性判断
        if 'arguments' in body_json and isinstance(body_json['arguments'], str):
             # 如果有 'arguments'，就解析它
            args_dict = json.loads(body_json['arguments'])
        else:
            # 如果没有 'arguments'，就认为整个body就是参数字典
            args_dict = body_json

        req_body = ImageRequest(**args_dict)

    except (json.JSONDecodeError, ValidationError) as e:
        raw_body = await request.body()
        logging.error(f"LobeChat请求体解析失败: {e}, 原始Body: {raw_body.decode()}")
        raise HTTPException(status_code=400, detail=f"请求体解析失败: {e}")

    token = json.loads(x_lobe_plugin_settings).get("session_id") if x_lobe_plugin_settings else None
    if not token:
        raise HTTPException(status_code=401, detail="LobeChat认证头缺失")

    width, height = get_image_dimensions(req_body.model, req_body.aspect_ratio)
    logging.info(f"LobeChat插件收到请求: prompt='{req_body.prompt}', model='{req_body.model}', size='{width}x{height}'")
    try:
        image_urls = generate_images(prompt=req_body.prompt, refresh_token=token, model=req_body.model, width=width, height=height)
        output = "\n\n".join([f"![image]({url})" for url in image_urls])
        return Response(content=output, media_type="text/markdown")
    except Exception as e:
        logging.error(f"LobeChat请求处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)