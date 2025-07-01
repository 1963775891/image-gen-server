

"""图像生成相关功能"""
import os
import requests
import time
from typing import Dict, List
import random
import logging
from google_crc32c import value as crc32c
import json

from . import utils
from .core import request, get_aws_v4_headers
from .exceptions import API_IMAGE_GENERATION_FAILED, API_CONTENT_FILTERED

MODEL_MAP = {
    "jimeng-3.0": "high_aes_general_v30l:general_v3.0_18b",
    "jimeng-2.1": "high_aes_general_v21_L:general_v2.1_L",
    "jimeng-2.0-pro": "high_aes_general_v20_L:general_v2.0_L",
    "jimeng-2.0": "high_aes_general_v20:general_v2.0",
    "jimeng-1.4": "high_aes_general_v14:general_v1.4",
    "jimeng-xl-pro": "text2img_xl_sft",
}
DEFAULT_MODEL = "jimeng-3.0"
DEFAULT_BLEND_MODEL = "jimeng-2.0-pro"
DRAFT_VERSION = "3.0.2"

def get_model_id(model_name: str, is_blend: bool) -> str:
    """根据模式获取模型ID"""
    if is_blend:
        return MODEL_MAP.get(DEFAULT_BLEND_MODEL)
    return MODEL_MAP.get(model_name, MODEL_MAP[DEFAULT_MODEL])

def get_file_content(file_path: str) -> bytes:
    """获取文件内容，支持本地和网络路径"""
    try:
        if file_path.startswith(('http://', 'https://')):
            response = requests.get(file_path, timeout=20)
            response.raise_for_status()
            return response.content
        else:
            if not os.path.exists(file_path):
                 raise FileNotFoundError(f"本地文件未找到: {file_path}")
            with open(file_path, 'rb') as f:
                return f.read()
    except Exception as e:
        raise ValueError(f"读取文件失败: {file_path}. 错误: {e}")

def _upload_file(file_content: bytes, refresh_token: str) -> str:
    """执行文件上传的完整流程"""
    auth_data = request("POST", "/mweb/v1/get_upload_token", refresh_token, data={"scene": 2})
    if not auth_data:
        raise API_IMAGE_GENERATION_FAILED("获取上传凭证失败，Token可能已失效")

    service_id = 'tb4s082cfz'
    params = {'Action': 'ApplyImageUpload', 'FileSize': len(file_content), 'ServiceId': service_id, 'Version': '2018-08-01'}
    headers = get_aws_v4_headers(
        auth_data['access_key_id'], auth_data['secret_access_key'],
        auth_data['session_token'], 'cn-north-1', 'imagex', 'imagex.bytedanceapi.com',
        'GET', '/', params
    )
    upload_address_data = request('GET', f"https://imagex.bytedanceapi.com/?{requests.utils.urlencode(params)}", refresh_token, headers=headers)
    upload_address = upload_address_data.get('Result', {}).get('UploadAddress', {})
    if not upload_address or not upload_address.get('StoreInfos'):
        raise API_IMAGE_GENERATION_FAILED(f"获取上传地址失败: {upload_address_data}")
    
    store_info = upload_address['StoreInfos'][0]
    upload_host = upload_address['UploadHosts'][0]
    upload_url = f"https://{upload_host}/{store_info['StoreUri']}"
    
    upload_headers = {'Authorization': store_info['Auth'], 'Content-Type': 'application/octet-stream', 'Content-Crc32': str(crc32c(file_content))}
    request('POST', upload_url, refresh_token, data=file_content, headers=upload_headers, is_json=False)

    commit_params = {'Action': 'CommitImageUpload', 'ServiceId': service_id, 'Version': '2018-08-01'}
    commit_payload = json.dumps({'SessionKey': upload_address['SessionKey']}).encode('utf-8')
    commit_headers = get_aws_v4_headers(
        auth_data['access_key_id'], auth_data['secret_access_key'],
        auth_data['session_token'], 'cn-north-1', 'imagex', 'imagex.bytedanceapi.com',
        'POST', '/', commit_params, payload=commit_payload
    )
    commit_url = f"https://imagex.bytedanceapi.com/?{requests.utils.urlencode(commit_params)}"
    commit_result = request('POST', commit_url, refresh_token, data=json.loads(commit_payload), headers=commit_headers)
    
    uri = commit_result.get('Result', {}).get('Results', [{}])[0].get('Uri')
    if not uri:
        raise API_IMAGE_GENERATION_FAILED(f"提交上传失败: {commit_result}")

    return uri

def generate_images(
    prompt: str,
    refresh_token: str,
    model: str = DEFAULT_MODEL,
    file_path: str = None,
    width: int = 1024,
    height: int = 1024,
    sample_strength: float = 1
    negative_prompt: str = ""
) -> List[str]:
    """
    生成图像，支持文生图和图生图。

    Args:
        prompt (str): 图片的文本描述。
        refresh_token (str): 即梦的session_id，支持多个，用逗号分隔。
        model (str, optional): 使用的模型名称。默认为 "jimeng-3.0"。
        file_path (str, optional): 参考图的URL或本地路径，用于图生图。默认为 None。
        width (int, optional): 图像宽度。默认为 1024。
        height (int, optional): 图像高度。默认为 1024。
        sample_strength (float, optional): 精细度/采样强度。默认为 0.5。
        negative_prompt (str, optional): 反向提示词。默认为空字符串。

    Returns:
        List[str]: 生成的图像URL列表。

    Raises:
        API_IMAGE_GENERATION_FAILED: 图像生成失败。
        API_CONTENT_FILTERED: 内容由于合规问题被过滤。
        ValueError: 如果prompt或refresh_token为空。
    """
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if not refresh_token:
        raise ValueError("refresh_token is required")

    is_blend_mode, upload_uri = bool(file_path), None
    if is_blend_mode:
        logging.info(f"进入图生图模式，参考图: {file_path}")
        try:
            file_content = get_file_content(file_path)
            upload_uri = _upload_file(file_content, refresh_token)
            logging.info(f"文件上传成功, URI: {upload_uri}")
        except Exception as e:
            raise API_IMAGE_GENERATION_FAILED(f"处理参考图失败: {e}")

    model_id = get_model_id(model, is_blend_mode)
    logging.info(f"选用模型: {model_id}")

    component_id = utils.generate_uuid()
    abilities = {}
    if is_blend_mode:
        abilities = {"blend": {"id": utils.generate_uuid(), "core_param": {"id": utils.generate_uuid(), "model": model_id, "prompt": prompt + '##', "sample_strength": sample_strength, "image_ratio": 1, "large_image_info": {"id": utils.generate_uuid(), "height": height, "width": width, "resolution_type": '1k'}}, "ability_list": [{"id": utils.generate_uuid(), "name": "byte_edit", "image_uri_list": [upload_uri], "image_list": [{"id": utils.generate_uuid(), "source_from": "upload", "image_uri": upload_uri, "uri": upload_uri}], "strength": 0.5}], "history_option": {"id": utils.generate_uuid()}}}
    else:
        abilities = {"generate": {"id": utils.generate_uuid(), "core_param": {"id": utils.generate_uuid(), "model": model_id, "prompt": prompt, "negative_prompt": negative_prompt, "seed": int(random.random() * 100000000) + 2500000000, "sample_strength": sample_strength, "image_ratio": 1, "large_image_info": {"id": utils.generate_uuid(), "height": height, "width": width}}, "history_option": {"id": utils.generate_uuid()}}}

    draft_content = {"type": "draft", "id": utils.generate_uuid(), "min_version": DRAFT_VERSION, "is_from_tsn": True, "version": DRAFT_VERSION, "main_component_id": component_id, "component_list": [{"type": "image_base_component", "id": component_id, "min_version": DRAFT_VERSION, "generate_type": "blend" if is_blend_mode else "generate", "aigc_mode": "workbench", "abilities": {"id": utils.generate_uuid(), **abilities}}]}
    babi_param_scenario = "to_image_referenceimage_generate" if is_blend_mode else "aigc_to_image"
    babi_param = utils.url_encode(utils.json_encode({"scenario": "image_video_generation", "feature_key": babi_param_scenario, "feature_entrance": "to_image", "feature_entrance_detail": f"to_image-{model_id}"}))
    data = {"extend": {"root_model": model_id, "template_id": ""}, "submit_id": utils.generate_uuid(), "metrics_extra": utils.json_encode({"generateCount": 1, "promptSource": "custom"}), "draft_content": utils.json_encode(draft_content)}

    result = request("POST", "/mweb/v1/aigc_draft/generate", refresh_token, params={"babi_param": babi_param}, data=data)

    history_id = result.get('aigc_data', {}).get('history_record_id')
    if not history_id:
        raise API_IMAGE_GENERATION_FAILED(f"未能获取到历史记录ID: {result}")

    status, fail_code, item_list = 20, None, []
    for _ in range(30):
        time.sleep(1)
        result = request("POST", "/mweb/v1/get_history_by_ids", refresh_token, data={"history_ids": [history_id]})
        record = result.get(history_id)
        if not record:
            continue
        status = record.get('status')
        if status != 20:
            fail_code, item_list = record.get('fail_code'), record.get('item_list', [])
            break

    if status == 30:
        if fail_code == '2038':
            raise API_CONTENT_FILTERED()
        raise API_IMAGE_GENERATION_FAILED(f"图像生成失败，状态码: {status}, 失败码: {fail_code}")
    if not item_list:
        raise API_IMAGE_GENERATION_FAILED("生成任务完成，但未返回图片列表")

    image_urls = []
    for item in item_list:
        if item:
            url = (item.get('image', {}).get('large_images', [{}])[0].get('image_url') or item.get('common_attr', {}).get('cover_url'))
            if url:
                image_urls.append(url)

    return image_urls