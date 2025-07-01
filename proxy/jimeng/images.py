"""
图像生成相关功能 - 已重构为“文生图”专用最终完美版
"""
import time
from typing import List
import random
import logging
import json

from . import utils
from .core import request
from .exceptions import API_IMAGE_GENERATION_FAILED, API_CONTENT_FILTERED

# --- 终极修改：移除所有下架和有问题的模型 ---
MODEL_MAP = {
    "jimeng-3.0": "high_aes_general_v30l:general_v3.0_18b",
    "jimeng-2.1": "high_aes_general_v21_L:general_v2.1_L",
    "jimeng-2.0-pro": "high_aes_general_v20_L:general_v2.0_L",
}
DEFAULT_MODEL = "jimeng-3.0"
DRAFT_VERSION = "3.0.2"

def generate_images(
    prompt: str,
    refresh_token: str,
    model: str = DEFAULT_MODEL,
    width: int = 1024,
    height: int = 1024,
    file_path: str = None, # 兼容参数，但已禁用
) -> List[str]:
    if file_path:
        raise API_IMAGE_GENERATION_FAILED("此版本已禁用图生图功能。")

    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if not refresh_token:
        raise ValueError("refresh_token is required")

    model_id = MODEL_MAP.get(model, MODEL_MAP[DEFAULT_MODEL])

    component_id = utils.generate_uuid()
    core_param = {
        "id": utils.generate_uuid(), "model": model_id, "prompt": prompt, 
        "negative_prompt": "", "seed": random.randint(2500000000, 3500000000), 
        "sample_strength": 1.0, "image_ratio": 1, 
        "large_image_info": {"id": utils.generate_uuid(), "height": height, "width": width}
    }
    abilities = {"generate": {"id": utils.generate_uuid(), "core_param": core_param, "history_option": {"id": utils.generate_uuid()}}}
    draft_content = {"type": "draft", "id": utils.generate_uuid(), "min_version": DRAFT_VERSION, "is_from_tsn": True, "version": DRAFT_VERSION, "main_component_id": component_id, "component_list": [{"type": "image_base_component", "id": component_id, "min_version": DRAFT_VERSION, "generate_type": "generate", "aigc_mode": "workbench", "abilities": {"id": utils.generate_uuid(), **abilities}}]}
    babi_param = utils.url_encode(utils.json_encode({"scenario": "image_video_generation", "feature_key": "aigc_to_image", "feature_entrance": "to_image", "feature_entrance_detail": f"to_image-{model_id}"}))
    data = {"extend": {"root_model": model_id, "template_id": ""}, "submit_id": utils.generate_uuid(), "metrics_extra": utils.json_encode({"generateCount": 1, "promptSource": "custom"}), "draft_content": utils.json_encode(draft_content)}

    result = request("POST", "/mweb/v1/aigc_draft/generate", refresh_token, params={"babi_param": babi_param}, data=data)

    history_id = result.get('aigc_data', {}).get('history_record_id')
    if not history_id:
        raise API_IMAGE_GENERATION_FAILED(f"未能获取到历史记录ID: {result}")

    for _ in range(120):
        time.sleep(1)
        poll_result = request("POST", "/mweb/v1/get_history_by_ids", refresh_token, data={"history_ids": [history_id]})
        record = poll_result.get(str(history_id))
        if record and record.get('status') != 20:
            if record.get('status') == 30:
                raise API_IMAGE_GENERATION_FAILED(f"图像生成失败，状态码: {record.get('status')}, 失败码: {record.get('fail_code')}")

            item_list = record.get('item_list', [])
            if not item_list: continue

            image_urls = [item.get('image', {}).get('large_images', [{}])[0].get('image_url') 
                          for item in item_list if item and item.get('image', {}).get('large_images', [{}])[0].get('image_url')]
            if image_urls:
                return image_urls

    raise API_IMAGE_GENERATION_FAILED("轮询超时，未能在120秒内获取到生成的图片。")