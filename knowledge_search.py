import logging
import os

import openai

logger = logging.getLogger(__name__)

SEARCH_SYSTEM_PROMPT = (
    '你是一个专业的学术论文分析助手。请基于提供的论文片段回答用户问题。'
    '用中文回答，引用具体的论文名称和章节，比较不同论文的观点异同。'
    '如果提供的片段不足以回答问题，请如实说明。'
)


def search(query, n_results=5):
    try:
        from knowledge_store import get_collection, embed_texts

        collection = get_collection()
        query_emb = embed_texts([query])[0]
        results = collection.query(query_embeddings=[query_emb], n_results=n_results)

        chunks = []
        ids_list = results['ids'][0] if results['ids'] else []
        docs_list = results['documents'][0] if results['documents'] else []
        metas_list = results['metadatas'][0] if results['metadatas'] else []
        dists_list = results['distances'][0] if results.get('distances') else []

        for i in range(len(ids_list)):
            chunks.append({
                'id': ids_list[i],
                'text': docs_list[i] if i < len(docs_list) else '',
                'metadata': metas_list[i] if i < len(metas_list) else {},
                'score': round(1.0 - dists_list[i] / 2.0, 4) if i < len(dists_list) and dists_list[i] is not None else None,
            })
        return chunks
    except Exception as e:
        logger.error('知识库搜索失败: %s', e)
        return []


def keyword_search(query, n_results=5):
    import db
    rows, _ = db.get_history(page=1, per_page=10000)
    results = []
    keywords = query.lower().split()
    for paper in rows:
        content = paper.get('full_analysis', '') or ''
        if not content:
            continue
        score = sum(content.lower().count(kw) for kw in keywords)
        if score > 0:
            results.append((score, paper))
    results.sort(key=lambda x: x[0], reverse=True)
    chunks = []
    for score, paper in results[:n_results]:
        chunks.append({
            'id': paper['arxiv_id'],
            'text': paper['full_analysis'][:2000] if paper.get('full_analysis') else '',
            'metadata': {
                'arxiv_id': paper['arxiv_id'],
                'title': paper.get('title', ''),
                'section': '关键词匹配',
            },
            'score': score,
        })
    return chunks


def synthesize_answer(query, chunks, model=None):
    if model is None:
        model = os.environ.get('DEFAULT_MODEL', 'deepseek-chat')

    api_key = os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')

    if not chunks:
        return '未在知识库中找到相关内容。请先对论文进行全文分析后再搜索，或尝试其他关键词。'

    context = '\n\n---\n\n'.join(
        f"【论文：{c['metadata'].get('title', '未知')} | 章节：{c['metadata'].get('section', '未知')}】\n{c['text']}"
        for c in chunks
    )

    prompt = f'论文片段：\n\n{context}\n\n用户问题：{query}\n\n请综合分析回答：'

    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url if base_url != 'https://api.openai.com/v1' else None,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SEARCH_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error('综合回答失败: %s', e)
        lines = [f'**检索到 {len(chunks)} 个相关片段（AI 综合暂不可用）**\n']
        for c in chunks:
            lines.append(
                f"- **{c['metadata'].get('title', '未知')}** "
                f"({c['metadata'].get('section', '')})"
            )
        return '\n'.join(lines)
