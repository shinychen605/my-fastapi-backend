import html
import os
import re
import requests
from openai import OpenAI

SYSTEM_PROMPT = '【系统提示词】你是一位专业的播客内容分析师。请根据用户上传的播客逐字稿，生成一份结构严谨、信息密集的中文摘要。\n\n处理要求：\n1. 标题：简洁、吸引人、概括核心主题（最多25字）\n2. 引言：1-2句话，包含主题、核心问题、主要嘉宾/主持人\n3. 核心内容：\n- 按逻辑归类，不按时间顺序\n- 每个论点必须保留支撑细节（数据、案例、逻辑）\n- 加粗重要术语、核心数据、关键结论\n- 二级标题加粗（用加粗标记）\n- 每个案例必须包含：背景、主体、情节、结果\n4. 结论：1-2句话最核心takeaway\n5. 语言：纯中文，专业流畅客观\n禁止出现：\n- 任何引用标记（如"根据xxx"、"来源：xxx"）\n- 任何版权文字的直接引用\n- "根据上传文件"、"资料显示"等来源痕迹\n- 纯口头禅、语气词\n覆盖率自检：\n- 所有重要论点必须写入正文\n- 未写入的案例必须列出并说明排除理由\n- 不确定的内容用【不确定】标注\n输出格式：直接输出HTML字符串，不要输出markdown。\nHTML结构模板（直接使用，不需要修改）：\n```html\n<h1>【标题】</h1>\n<h2>【副标题】</h2>\n<p>【引言】</p>\n<p>【嘉宾/时长/适合人群】</p>\n<div>【正文HTML内容，按section分段落】</div>\n```'

BASE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f5f5f5;color:#1a1a1a;min-height:100vh;padding:24px 16px 80px;line-height:1.7}
.container{max-width:720px;margin:0 auto}
.card{background:#fff;border-radius:16px;padding:28px 24px;box-shadow:0 8px 24px rgba(0,0,0,.05)}
.back{font-size:14px;color:#c89a00;text-decoration:none;margin-bottom:16px;display:inline-block}
.back:hover{opacity:.86}
h1{font-size:28px;line-height:1.3;margin-bottom:12px}
h2{font-size:20px;line-height:1.4;margin:24px 0 12px;font-weight:700}
h3{font-size:17px;line-height:1.5;margin:18px 0 10px;font-weight:700}
p{font-size:15px;color:#333;margin:0 0 14px}
section{margin-top:20px}
ul,ol{padding-left:20px;margin:0 0 14px}
li{margin-bottom:8px;color:#333}
strong{color:#111}
a{color:#c89a00}
.meta{font-size:13px;color:#666;margin-bottom:18px}
blockquote{border-left:4px solid #c89a00;background:#fffaf0;padding:12px 14px;border-radius:8px;margin:16px 0}
code{background:#f7f7f7;padding:2px 6px;border-radius:6px}
hr{border:none;border-top:1px solid #eee;margin:20px 0}
</style>
</head>
<body>
<div class="container">
<a href="/" class="back">← 上传播客文稿</a>
<div class="card">
{content}
</div>
</div>
</body>
</html>"""

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
MAX_INPUT_CHARS = int(os.getenv('MAX_INPUT_CHARS', '200000'))


def _extract_title(content: str) -> str:
    match = re.search(r'<h1[^>]*>(.*?)</h1>', content, flags=re.I | re.S)
    if match:
        title = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if title:
            return title[:60]
    return '播客摘要'


def _wrap_full_html(content: str) -> str:
    if re.search(r'<html[\s>]', content, flags=re.I):
        return content
    title = html.escape(_extract_title(content))
    return BASE_HTML_TEMPLATE.format(title=title, content=content)


def summarize_text(text: str) -> str:
    if text is None or not text.strip():
        raise ValueError('text 不能为空')

    truncated_text = text[:MAX_INPUT_CHARS]
    api_key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('缺少环境变量 DEEPSEEK_API_KEY')

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': truncated_text},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    content = (response.choices[0].message.content or '').strip()
    if not content:
        raise RuntimeError('AI 未返回有效内容')
    return _wrap_full_html(content)


def create_gist(html: str, title: str = 'podmemo-summary') -> str:
    """通过 GitHub Gist 创建永久可分享链接；失败时返回空字符串。"""
    gist_token = os.getenv('GITHUB_TOKEN', '').strip()
    if not gist_token:
        return ''

    safe_title = re.sub(r'[^\w\-一-鿿]+', '-', title).strip('-') or 'podmemo-summary'
    payload = {
        'description': f'PodMemo 播客摘要 | {safe_title}',
        'public': True,
        'files': {f"{safe_title[:30]}.html": {'content': html}},
    }
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {gist_token}',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    try:
        resp = requests.post('https://api.github.com/gists', json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            return resp.json().get('html_url', '') or ''
    except requests.RequestException:
        return ''
    return ''
