import os, re, datetime, base64
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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
    '- 任何版权文字的直接引用\n\n'
    '输出格式：直接输出HTML字符串（不要输出markdown，不要用代码块包裹）。\n'
    '重要：直接输出HTML内容，不要加 ```html 或 ``` 等标记。'
)

BACK_URL = os.getenv('BACK_URL', 'https://podcast-summary-9qm7g8sfw-shinychen605s-projects.vercel.app')
BACK_LABEL = os.getenv('BACK_LABEL', '← 播客摘要库')
VERCEL_TOKEN = os.getenv('VERCEL_TOKEN', '').strip()

app = FastAPI(title='PodMemo API', version='1.8.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

class SummarizeRequest(BaseModel):
    text: str = Field(..., description='播客逐字稿全文')

class SummarizeResponse(BaseModel):
    html: str
    share_url: str

@app.get('/health')
def health(): return {'status': 'ok'}

@app.post('/api/summarize', response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail='text 不能为空')
    text = req.text[:int(os.getenv('MAX_INPUT_CHARS', '200000'))]
    api_key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    if not api_key:
        raise HTTPException(status_code=500, detail='缺少 DEEPSEEK_API_KEY')

    client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com')
    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': text}],
        temperature=0.3, max_tokens=4000,
    )
    raw = (resp.choices[0].message.content or '').strip()
    if not raw:
        raise HTTPException(status_code=502, detail='AI 未返回有效内容')

    # 清理 markdown 代码块
    raw = re.sub(r'^```html\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'^```\s*$', '', raw, flags=re.MULTILINE)
    html = raw.replace('{', '&#123;').replace('}', '&#125;')
    title = re.sub(r'<[^>]*>', '', raw[:60]).strip() or f'播客摘要-{datetime.datetime.now().strftime("%m%d%H%M")}'
    title_esc = title.replace('<', '&lt;').replace('>', '&gt;')

    if '<html' not in html.lower():
        html = (
            '<!DOCTYPE html><html lang="zh"><head>'
            '<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>'
            f'<title>{title_esc}</title>'
            '</head><body>'
            f'<div style="max-width:720px;margin:0 auto;padding:20px 20px 60px">'
            f'<a href="{BACK_URL}" style="display:inline-block;margin:16px 0;font-size:14px;color:#c89a00;text-decoration:none">{BACK_LABEL}</a>'
            f'<h1 style="font-size:22px;font-weight:700;margin-bottom:16px">{title_esc}</h1>'
            f'{html}'
            '</div></body></html>'
        )
    else:
        back_tag = f'<a href="{BACK_URL}" style="display:inline-block;margin:16px 20px 0;font-size:14px;color:#c89a00;text-decoration:none">{BACK_LABEL}</a>'
        html = html.replace('<body>', '<body>' + back_tag, 1)

    # 1. Gist 分享链接（用旧的 gist-only token）
    gist_token = os.getenv('GITHUB_TOKEN', '').strip()
    share_url = ''
    if gist_token:
        try:
            gr = requests.post(
                'https://api.github.com/gists',
                headers={'Authorization': f'Bearer {gist_token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
                json={'description': f'PodMemo | {title}', 'public': True, 'files': {f"{title[:50]}.html": {'content': html}}},
                timeout=15,
            )
            if gr.status_code in (200, 201):
                share_url = gr.json().get('html_url', '') or ''
        except Exception:
            pass

    # 2. 推送到 GitHub 仓库（用新的 repo-token）
    repo_token = os.getenv('GH_REPO_TOKEN', '').strip()
    repo = os.getenv('GITHUB_REPO', '').strip() or 'shinychen605/podcast-summary'
    if repo_token:
        try:
            filename = f"{title[:40]}.html"
            api_url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            hdrs = {'Authorization': f'Bearer {repo_token}', 'Accept': 'application/vnd.github.v3+json'}
            # 获取已存在的sha
            get_r = requests.get(api_url, headers=hdrs, timeout=10)
            sha = get_r.json().get('sha') if get_r.status_code == 200 else None
            put_data = {'message': f'Add summary: {title}', 'content': base64.b64encode(html.encode()).decode()}
            if sha: put_data['sha'] = sha
            requests.put(api_url, headers=hdrs, json=put_data, timeout=15)

            # 3. 更新 index.html 索引
            idx_url = f"https://api.github.com/repos/{repo}/contents/index.html"
            get_idx = requests.get(idx_url, headers=hdrs, timeout=10)
            if get_idx.status_code == 200:
                idx_content = base64.b64decode(get_idx.json()['content']).decode('utf-8')
                today = datetime.date.today().strftime('%m-%d')
                new_item = f'    <div class="item">\n      <span class="item-date">{today}</span>\n      <a class="item-title" href="{filename}">{title_esc}</a>\n    </div>'
                if filename not in idx_content and '<div class="item">' in idx_content:
                    idx_content = idx_content.replace('<div class="item">', new_item + '\n    <div class="item">', 1)
                    idx_data = {
                        'message': f'Update index: add {title}',
                        'content': base64.b64encode(idx_content.encode()).decode(),
                        'sha': get_idx.json().get('sha'),
                    }
                    requests.put(idx_url, headers=hdrs, json=idx_data, timeout=15)
        except Exception as e:
            print(f"GitHub push failed: {e}")

    # 4. 触发 Vercel 重新部署
    if VERCEL_TOKEN and repo:
        try:
            requests.post(
                'https://api.vercel.com/v13/deployments',
                headers={'Authorization': f'Bearer {VERCEL_TOKEN}', 'Content-Type': 'application/json'},
                json={'gitSource': {'type': 'github', 'repo': repo}},
                timeout=10,
            )
        except Exception:
            pass

    return SummarizeResponse(html=html, share_url=share_url)
