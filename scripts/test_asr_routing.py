# -*- coding: utf-8 -*-
"""
验证「语音听写」与「语音转写」两套凭据互不抢占。

做法：临时插一条优先级更高（priority=1）的 xfyun_lfasr 配置，
      如果选路没有正确排除，resolve_xfyun_credentials() 就会挑中它，
      语音输入会跟着坏掉。

跑完会自动删掉这条临时数据。
"""
import re
import sys

import pymysql

sys.path.insert(0, r'E:\学习资源\背书工具\beibei-agent')

ENV = r'E:\学习资源\背书工具\beibei-agent\.env'
env = {}
for line in open(ENV, encoding='utf-8'):
    m = re.match(r'\s*([A-Z_]+)\s*=\s*(.*)', line)
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"').strip("'")

conn = pymysql.connect(
    host=env['MYSQL_HOST'], port=int(env['MYSQL_PORT']), user=env['MYSQL_USER'],
    password=env['MYSQL_PASSWORD'], database=env['MYSQL_DB'], charset='utf8mb4',
)
cur = conn.cursor()

# 找到语音听写那条，作为凭据来源
cur.execute("SELECT id FROM bb_ai_provider WHERE vendor='xfyun' AND capability LIKE '%ASR%' LIMIT 1")
row = cur.fetchone()
if not row:
    print('找不到语音听写配置，无法测试')
    raise SystemExit(1)
iat_id = row[0]

cur.execute("DELETE FROM bb_ai_provider WHERE remark='TEMP-TEST-LFASR'")
cur.execute(
    "INSERT INTO bb_ai_provider "
    "(name, vendor, protocol, base_url, model, api_key_enc, api_secret_enc, app_id, "
    " capability, enabled, priority, locked, remark) "
    "SELECT '测试·讯飞语音转写', 'xfyun_lfasr', 'custom', 'https://raasr.xfyun.cn/api', 'lfasr', "
    "       api_key_enc, api_secret_enc, app_id, 'ASR', 1, 1, 0, 'TEMP-TEST-LFASR' "
    "FROM bb_ai_provider WHERE id = %s",
    (iat_id,),
)
conn.commit()
cur.execute("SELECT id FROM bb_ai_provider WHERE remark='TEMP-TEST-LFASR'")
lfasr_id = cur.fetchone()[0]
print('临时插入语音转写配置 id=%s（priority=1，比语音听写更靠前）' % lfasr_id)
print()

import importlib  # noqa: E402

from app.services import asr as asr_mod  # noqa: E402
from app.services import interview_note as note_mod  # noqa: E402

importlib.reload(asr_mod)
importlib.reload(note_mod)

print('===== resolve_xfyun_credentials()（语音输入用）=====')
c1 = asr_mod.resolve_xfyun_credentials()
print('  来源   :', c1.source)
print('  base   :', c1.base_url)
ok1 = 'raasr' not in (c1.base_url or '') and '语音转写' not in (c1.source or '')
print('  结论   :', '✅ 没被语音转写抢走' if ok1 else '🔴 被抢走了！')

print()
print('===== resolve_lfasr_credentials()（面经用）=====')
c2 = note_mod.resolve_lfasr_credentials()
if c2 is None:
    print('  🔴 没找到')
    ok2 = False
else:
    print('  来源   :', c2.source)
    print('  base   :', c2.base_url)
    ok2 = 'raasr' in c2.base_url
    print('  结论   :', '✅ 正确指向语音转写端点' if ok2 else '🔴 端点不对')

# 清理
cur.execute("DELETE FROM bb_ai_provider WHERE remark='TEMP-TEST-LFASR'")
conn.commit()
cur.execute("SELECT COUNT(*) FROM bb_ai_provider WHERE remark='TEMP-TEST-LFASR'")
print()
print('临时数据已清理:', cur.fetchone()[0] == 0)
conn.close()

print()
print('总计:', '通过' if (ok1 and ok2) else '失败')
raise SystemExit(0 if (ok1 and ok2) else 1)
