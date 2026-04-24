import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from summarize import summarize_text, create_gist

app = FastAPI(title='PodMemo API', version='1.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

MAX_INPUT_CHARS = int(os.getenv('MAX_INPUT_CHARS', '200000'))


class SummarizeRequest(BaseModel):
    text: str = Field(..., description='播客逐字稿全文（字符串）')


class SummarizeResponse(BaseModel):
    html: str
    share_url: str


def _extract_title_from_html(html: str) -> str:
    match = re.search(r'<title[^>]*>(.*?)</title>', html, flags=re.I | re.S)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return 'podmemo-summary'


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/api/summarize', response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    if req.text is None or not req.text.strip():
        raise HTTPException(status_code=400, detail='text 不能为空')

    text = req.text[:MAX_INPUT_CHARS]
    try:
        html = summarize_text(text)
        if not html:
            raise HTTPException(status_code=502, detail='AI 未返回有效 HTML 内容')
        title = _extract_title_from_html(html)
        share_url = create_gist(html, title=title)
        return SummarizeResponse(html=html, share_url=share_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'AI 调用失败：{e}')
