# GITHUB: https://github.com/fengin/image-gen-server.git
# 相关知识可以看AI全书：https://aibook.ren
# 由AI助手修改和增强

"""核心功能实现"""
import json
import time
import hmac
import hashlib
from typing import Any, Dict, Optional
import requests
import logging
import gzip
import brotli
from io import BytesIO
import random

from . import utils
from .exceptions import API_REQUEST_FAILED, API_IMAGE_GENERATION_INSUFFICIENT_POINTS

MODEL_NAME = "jimeng"
DEFAULT_ASSISTANT_ID = "513695"
VERSION_CODE = "5.8.0"
PLATFORM_CODE = "7"
DEVICE_ID = utils.generate_device_id()
WEB_ID = utils.generate_web_id()
USER_ID = utils.generate_uuid(False)

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate", 
    "Accept-language": "zh-CN,zh;q=0.9", "Cache-control": "no-cache",
    "Appid": DEFAULT_ASSISTANT_ID, "Appvr": VERSION_CODE, "Origin": "https://jimeng.jianying.com",
    "Pragma": "no-cache", "Priority": "u=1, i", "Referer": "https://jimeng.jianying.com",
    "Pf": PLATFORM_CODE, "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"', "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

def acquire_token(refresh_token: str) -> str:
    tokens = [t.strip() for t in refresh_token.split(',') if t.strip()]
    if not tokens:
        raise ValueError("refresh_token is empty or invalid.")
    return random.choice(tokens)

def decompress_response(response: requests.Response) -> str:
    content = response.content
    encoding = response.headers.get('Content-Encoding', '').lower()

    if encoding == 'gzip':
        try:
            # --- 关键修改在这里：增加 try...except ---
            buffer = BytesIO(content)
            with gzip.GzipFile(fileobj=buffer) as f:
                content = f.read()
        except gzip.BadGzipFile:
            # 如果解压失败，就认为它本来就是普通文本，直接使用原始数据
            logging.warning("Received a response with 'gzip' encoding header but it was not a valid gzip file. Treating as plain text.")
            pass # content 保持原始数据不变

    elif encoding == 'br': 
        try:
            content = brotli.decompress(content)
        except brotli.Error:
            logging.warning("Received a response with 'br' encoding header but it failed to decompress. Treating as plain text.")
            pass # content 保持原始数据不变

    return content.decode('utf-8', errors='ignore')

def request(
    method: str,
    uri: str,
    refresh_token: str,
    params: Optional[Dict] = None,
    data: Optional[Any] = None,
    headers: Optional[Dict] = None,
    is_json=True,
    **kwargs
) -> Dict[str, Any]:
    token = acquire_token(refresh_token)

    full_url = uri if uri.startswith('https://') else f"https://jimeng.jianying.com{uri}"

    _headers = {**FAKE_HEADERS, "Cookie": f"sessionid={token}; sessionid_ss={token}; sid_tt={token};"}
    if headers: 
        _headers.update(headers)

    if not uri.startswith('https://'):
        device_time = utils.get_timestamp()
        sign = utils.md5(f"9e2c|{uri[-7:]}|{PLATFORM_CODE}|{VERSION_CODE}|{device_time}||11ac")
        _headers.update({"Device-Time": str(device_time), "Sign": sign, "Sign-Ver": "1"})

    _params = {}
    if not uri.startswith('https://'):
         _params.update({"aid": DEFAULT_ASSISTANT_ID, "device_platform": "web", "region": "CN", "web_id": WEB_ID})
    if params: 
        _params.update(params)

    try:
        response = requests.request(method=method.lower(), url=full_url, params=_params, data=data if is_json is False else None, json=data if is_json is True else None, headers=_headers, timeout=30, **kwargs)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '')
        if 'application/json' in content_type:
            result_text = decompress_response(response)
            result = json.loads(result_text)

            ret = result.get('ret')
            if ret is not None and str(ret) != '0':
                if str(ret) == '5000': 
                    raise API_IMAGE_GENERATION_INSUFFICIENT_POINTS(f"即梦积分可能不足: {result.get('errmsg')}")
                raise API_REQUEST_FAILED(f"请求失败: {result.get('errmsg')} (code: {ret})")

            return result.get('data') if 'data' in result else result
        else: 
            return {'raw_response': response}

    except requests.exceptions.RequestException as e: 
        raise API_REQUEST_FAILED(f"网络错误: {e}")
    except json.JSONDecodeError: 
        raise API_REQUEST_FAILED("响应格式错误，无法解析JSON")
    except Exception as e: 
        raise e

def _hmac_sha256(key: bytes, msg: str) -> bytes: 
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

def get_aws_v4_headers(access_key, secret_key, session_token, region, service, host, method, path, params, payload=b''):
    amz_date = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    date_stamp = time.strftime('%Y%m%d', time.gmtime())

    canonical_querystring = '&'.join(f"{key}={requests.utils.quote(str(val))}" for key, val in sorted(params.items()))

    payload_hash = hashlib.sha256(payload).hexdigest()

    canonical_headers = f'host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\nx-amz-security-token:{session_token}\n'
    signed_headers = 'host;x-amz-content-sha256;x-amz-date;x-amz-security-token'

    canonical_request = '\n'.join([method, path, canonical_querystring, canonical_headers, signed_headers, payload_hash])

    credential_scope = f'{date_stamp}/{region}/{service}/aws4_request'

    string_to_sign = '\n'.join(['AWS4-HMAC-SHA256', amz_date, credential_scope, hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()])

    k_date = _hmac_sha256(('AWS4' + secret_key).encode('utf-8'), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, 'aws4_request')

    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    return {
        'Host': host, 
        'X-Amz-Date': amz_date, 
        'X-Amz-Security-Token': session_token, 
        'X-Amz-Content-Sha256': payload_hash, 
        'Authorization': f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}", 
        'Content-Type': 'application/json' if payload else ''
    }