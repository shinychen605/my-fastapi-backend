import html
import os
import re
import requests
from openai import OpenAI

SYSTEM_PROMPT = (
    '【系统提示词】你是一位专业的播客内容分析师。请根据用户上传的播客逐字稿，'
    '生成一份结构严谨、信息密集的中文摘要。\n\n'
    '处理要求：\n'
    '1. 标题：简洁、吸引人、概括核心主题（最多25字）\n'
    '2. 引言：1-2句话，包含主题、核心问题、主要嘉宾/主持人\n'
    '3. 核心内容：\n'
    '- 按逻辑归类，不按时间顺序\n'
    '- 每个论点必须保留支撑细节（数据、案例、逻辑）\n'
    '- 加粗重要术语、核心数据、关键结论\n'
    '- 二级标题加粗（用加粗标记）\n'
    '- 每个案例必须包含：背景、主体、情节、结果\n'
    '4. 结论：1-2句话最核心takeaway\n'
    '5. 语言：纯中文，专业流畅客观\n\n'
    '禁止出现：\n'
    '- 任何引用标记（如"根据xxx"、"来源：xxx"）\n'
    '- 任何版权文字的直接引用\n'
    '- "根据上传文件"、"资料显示"等来源痕迹\n'
    '- 纯口头禅、语气词\n\n'
    '覆盖率自检：\n'
    '- 所有重要论点必须写入正文\n'
    '- 未写入的案例必须列出并说明排除理由\n'
    '- 不确定的内容用【不确定】标注\n\n'
    '输出格式：直接输出HTML字符串，不要输出markdown。\n'
    'HTML结构模板（直接使用，不需要修改）：\n'
    '<h1>【标题】</h1>\n'
    '<h2>【副标题】</h2>\n'
    '<p>【引言】</p>\n'
    '<p>【嘉宾/时长/适合人群】</p>\n'
    '<div>【正文HTML内容，按section分段落】</div>'
)

BASE_HTML_TEMPLATE = (
    '<!DOCTYPE html>\n'
    '<html lang="zh">\n'
    '<head>\n'
    '<meta charset="UTF-8"/>\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
    '<title>{TITLE}</title>\n'
    '<style>\n'
    '*{{margin:0;padding:0;box-sizing:border-box}}\n'
    'body{{font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;background:#f5f5f5;color:#1a1a1a;min-height:100vh;padding:24px 16px 80px;line-height:1.7}}\n'
    '.container{{max-width:720px;margin:0 auto}}\n'
    '.card{{background:#fff;border-radius:16px;padding:28px 24px;box-shadow:0 8px 24px rgba(0,0,0,.05)}}\n'
    '.back{{font-size:14px;color:#c89a00;text-decoration:none;margin-bottom:16px;display:inline-block}}\n'
    '.back:hover{{opacity:.8}}\n'
    'h1{{font-size:28px;line-height:1.3;margin-bottom:12px}}\n'
    'h2{{font-size:20px;line-height:1.4;margin:24px 0 12px;font-weight:700}}\n'
    'h3{{font-size:17px;line-height:1.5;margin:18px 0 10px;font-weight:700}}\n'
    'p{{font-size:15px;color:#333;margin:0 0 14px}}\n'
    'section{{margin-top:20px}}\n'
    'ul,ol{{padding-left:20px;margin:0 0 14px}}\n'
    'li{{margin-bottom:8px;color:#333}}\n'
    'strong{{color:#111}}\n'
    'a{{color:#c89a00}}\n'
    '.meta{{font-size:13px;color:#666;margin-bottom:18px}}\n'
    'blockquote{{border-left:4px solid #c89a00;background:#fffaf0;padding:12px 14px;border-radius:8px;margin:16px 0}}\n'
    'code{{background:#f7f7f7;padding:2px 6px;border-radius:6px}}\n'
    'hr{{border:none;border-top:1px solid #eee;margin:20px 0}}\n'
    '</style>\n'
    '</head>\n'
    '<body>\n'
    '<div class="container">\n'
    '<a href="/" class="back">← 上传播客文稿</a>\n'
    '<div class="card">\n'
    '{CONTENT}\n'
    '</div>\n'
    '</div>\n'
    '</body>\n'
    '</html>'
)

DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
MAX_INPUT_CHARS = int(os.getenv('MAX_INPUT_CHARS', '200000'))


def _extract_title(content: str) -> str:
    m = re.search(r'<h1[^>]*>(.*?)</h1>', content, flags=re.I | re.S)
    if m:
        t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if t:
            return t[:60]
    return '播客摘要'


def _wrap_full_html(content: str) -> str:
    """如果内容已经是完整HTML页面则直接返回；否则包装成完整HTML。"""
    if re.search(r'<html[\s>]', content, flags=re.I):
        return content
    title = html.escape(_extract_title(content))
    # 用字符串替换代替 .format()，避免 { } 在 CSS 中引发 KeyError
    result = BASE_HTML_TEMPLATE.replace('{TITLE}', title).replace('{CONTENT}', content)
    return result


def summarize_text(text: str) -> str:
    if not text or not text.strip():
        raise ValueError('text 不能为空')

    truncated = text[:MAX_INPUT_CHARS]
    api_key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('缺少环境变量 DEEPSEEK_API_KEY')

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': truncated},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    raw = (resp.choices[0].message.content or '').strip()
    if not raw:
        raise RuntimeError('AI 未返回有效内容')
    return _wrap_full_html(raw)


def create_gist(html: str, title: str = 'podmemo-summary') -> str:
    """通过 GitHub Gist 创建永久可分享链接；失败时返回空字符串。"""
    token = os.getenv('GITHUB_TOKEN', '').strip()
    if not token:
        return ''
    safe = re.sub(r'[^\w\-一-鿿]+', '-', title).strip('-') or 'podmemo-summary'
    payload = {
        'description': f'PodMemo | {safe}',
        'public': True,
        'files': {f"{safe[:50]}.html": {'content': html}},
    }
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    try:
        r = requests.post('https://api.github.com/gists', json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            return r.json().get('html_url', '') or ''
    except requests.RequestException:
        pass
    return ''
