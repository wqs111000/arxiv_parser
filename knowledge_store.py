import logging
import os

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

CHROMA_PATH = 'data/chromadb'
COLLECTION_NAME = 'paper_chunks'

_embedding_client = None
_local_model = None
_chroma_client = None


def _use_local():
    base = os.environ.get('EMBEDDING_BASE_URL', '')
    if base == 'local':
        return True
    if base:
        return False
    return True


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        model_name = os.environ.get('EMBEDDING_MODEL', '') or 'BAAI/bge-small-zh-v1.5'
        logger.info('加载本地 embedding 模型: %s ...', model_name)
        _local_model = SentenceTransformer(model_name)
    return _local_model


def _get_embedding_client():
    global _embedding_client
    if _embedding_client is None:
        import openai
        api_key = os.environ.get('EMBEDDING_API_KEY', os.environ.get('OPENAI_API_KEY'))
        base_url = os.environ.get('EMBEDDING_BASE_URL', 'https://api.openai.com/v1')
        _embedding_client = openai.OpenAI(api_key=api_key, base_url=base_url)
    return _embedding_client


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        os.makedirs(CHROMA_PATH, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection():
    return _get_chroma().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={'hnsw:space': 'cosine'},
    )


def chunk_markdown(content, title, arxiv_id):
    sections = content.split('\n### ')
    chunks = []
    for i, section in enumerate(sections):
        if not section.strip():
            continue
        if i == 0:
            section_title = title
        else:
            parts = section.split('\n', 1)
            section_title = parts[0].strip()
            body = parts[1] if len(parts) > 1 else ''
            section = body.strip() if body else section

        if not section.strip():
            continue

        chunks.append({
            'text': f"## {title}\n### {section_title}\n\n{section[:3000]}",
            'metadata': {
                'arxiv_id': arxiv_id,
                'title': title[:500],
                'section': section_title[:300],
            },
        })
    return chunks


def embed_texts(texts, model=None):
    if _use_local():
        m = _get_local_model()
        embeddings = m.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    if model is None:
        model = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')
    client = _get_embedding_client()
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


def index_paper(arxiv_id, title, content):
    try:
        collection = get_collection()
        existing = collection.get(where={'arxiv_id': arxiv_id})
        if existing['ids']:
            collection.delete(ids=existing['ids'])

        chunks = chunk_markdown(content, title, arxiv_id)
        if not chunks:
            return 0

        texts = [c['text'] for c in chunks]
        embeddings = embed_texts(texts)
        ids = [f'{arxiv_id}_{i}' for i in range(len(chunks))]

        collection.add(
            embeddings=embeddings,
            documents=texts,
            metadatas=[c['metadata'] for c in chunks],
            ids=ids,
        )
        logger.info('已索引论文 %s，共 %d 个片段', arxiv_id, len(chunks))
        return len(chunks)
    except Exception as e:
        logger.error('索引论文失败 %s: %s', arxiv_id, e)
        return 0


def remove_paper_index(arxiv_id):
    try:
        collection = get_collection()
        existing = collection.get(where={'arxiv_id': arxiv_id})
        if existing['ids']:
            collection.delete(ids=existing['ids'])
    except Exception as e:
        logger.error('移除论文索引失败 %s: %s', arxiv_id, e)


def index_all_papers():
    import db
    from utils import load_analysis_from_md

    rows, _ = db.get_history(page=1, per_page=10000)
    indexed = 0
    for paper in rows:
        content = paper.get('full_analysis')
        if not content:
            content = load_analysis_from_md(paper.get('pdf_path'))
        if content:
            n = index_paper(paper['arxiv_id'], paper.get('title', ''), content)
            if n:
                indexed += 1
    return indexed


def get_index_stats():
    try:
        collection = get_collection()
        return {'total_chunks': collection.count(), 'mode': 'local' if _use_local() else 'api'}
    except Exception:
        return {'total_chunks': 0, 'mode': 'unknown'}
