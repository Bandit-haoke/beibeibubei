# -*- coding: utf-8 -*-
"""
探测讯飞【语音转写 LFASR】是否可用。

只调用 prepare 接口（不上传任何音频、不消耗转写时长），用于判断：
  - 凭据是否有效        -> err_no=26601 非法应用信息
  - 是否开通了该服务    -> err_no=26625 / 26633 服务时长不足
  - 角色分离是否开通    -> 通过 role_type 参数是否被接受间接判断

不会打印任何密钥。
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, r'E:\学习资源\背书工具\beibei-agent')

from app.services.asr import resolve_xfyun_credentials  # noqa: E402

LFASR_BASE = 'https://raasr.xfyun.cn/api'


def make_signa(app_id: str, secret_key: str, ts: str) -> str:
    base = app_id + ts
    md5 = hashlib.md5(base.encode('utf-8')).hexdigest()
    mac = hmac.new(secret_key.encode('utf-8'), md5.encode('utf-8'), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode('utf-8')


def post_form(path: str, params: dict) -> dict:
    url = LFASR_BASE + path
    body = urllib.parse.urlencode(params).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8')
    try:
        return json.loads(raw)
    except Exception:
        return {'_raw': raw[:500]}


def main() -> None:
    cred = resolve_xfyun_credentials()
    print('凭据字段:', cred._fields)
    print('app_id   :', (cred.app_id[:4] + '****') if cred.app_id else '(空)')
    print('来源     :', getattr(cred, 'source', '?'))
    print('api_key 长度:', len(cred.api_key or ''))
    print('api_secret 长度:', len(cred.api_secret or ''))
    print()

    if not cred.app_id or not cred.api_secret:
        print('[FAIL] app_id 或 api_secret 为空，无法测试')
        return

    ts = str(int(time.time()))
    signa = make_signa(cred.app_id, cred.api_secret, ts)

    # 基础探测：不带任何附加能力
    base = {
        'app_id': cred.app_id,
        'signa': signa,
        'ts': ts,
        'file_len': '1048576',
        'file_name': 'probe.mp3',
        'slice_num': '1',
    }
    print('===== 探测 1：基础 prepare =====')
    r1 = post_form('/prepare', base)
    print(json.dumps(r1, ensure_ascii=False, indent=2))
    print()

    if r1.get('ok') == 0:
        print('===== 探测 2：带角色分离参数 prepare =====')
        ts2 = str(int(time.time()))
        p2 = dict(base)
        p2['signa'] = make_signa(cred.app_id, cred.api_secret, ts2)
        p2['ts'] = ts2
        p2['has_seperate'] = 'true'
        p2['speaker_number'] = '2'
        p2['role_type'] = '1'
        p2['lfasr_type'] = '0'
        p2['has_smooth'] = 'true'
        p2['pd'] = 'tech'
        r2 = post_form('/prepare', p2)
        print(json.dumps(r2, ensure_ascii=False, indent=2))
        print()
        print('>>> 结论：语音转写服务【已开通】，可以走角色分离方案')
    else:
        err = r1.get('err_no')
        hint = {
            26601: '应用信息非法 —— app_id / secret_key 不匹配',
            26625: '服务时长不足 —— 你的应用**没有开通【语音转写】服务**，需去讯飞控制台领取/购买',
            26633: '音频服务时长不足 —— 同上，没有可用时长',
            26607: '语种未授权',
            26623: '音频格式受限',
        }.get(err, '未知错误，见上方返回')
        print('>>> 结论：不可用 ->', hint)


if __name__ == '__main__':
    main()
