"""Vector RAG foundations — Phase 2 of the AI upgrade strategy.

Replaces the static "dump up to 40 products every single turn" approach in
ai_context_engine.py with real semantic retrieval: only the few products/services
actually relevant to what the customer is asking RIGHT NOW get pulled into the prompt,
via MongoDB Atlas Vector Search — no new vendor needed, this app already runs on Atlas.

This is a FOUNDATION, not a full replacement yet:
- Requires an EMBEDDINGS_API_KEY (OpenAI-compatible embeddings endpoint) to be
  configured. It is NOT set in this environment yet — every function below degrades
  gracefully (returns None / [] / 0) when it isn't, so nothing breaks and the existing
  static-blob context in ai_context_engine.py keeps working exactly as before until
  this is deliberately turned on per environment.
- Requires the Atlas Vector Search index below to exist on business_knowledge.embedding.
  ensure_vector_index() attempts to create it programmatically (supported by recent
  pymongo on Atlas clusters that support Vector Search — M10+ generally, not all
  free/shared tiers), but may need to be created once manually via the Atlas UI
  (Search > Create Search Index > JSON Editor) if your cluster tier doesn't allow the
  driver to create it directly.
- Ingestion (reindex_business_knowledge) has to be triggered per business — there's a
  manual admin route for it (see app.py: /api/ai/reindex_knowledge). No automatic
  re-embed-on-product-edit trigger is wired up yet; that's the natural next step once
  this foundation is validated with real data.
"""

import os
import requests
from mongo_client import db, MONGO_STATUS

EMBEDDINGS_API_URL = os.environ.get('EMBEDDINGS_API_URL', 'https://api.openai.com/v1/embeddings')
EMBEDDINGS_MODEL = os.environ.get('EMBEDDINGS_MODEL', 'text-embedding-3-small')
VECTOR_INDEX_NAME = 'business_knowledge_vector_index'

# Atlas Vector Search index definition — create once per cluster via ensure_vector_index()
# below, or manually in the Atlas UI on the `business_knowledge` collection if your
# cluster tier doesn't support driver-created search indexes.
VECTOR_INDEX_DEFINITION = {
    "name": VECTOR_INDEX_NAME,
    "type": "vectorSearch",
    "definition": {
        "fields": [
            # 1536 = text-embedding-3-small's dimension. Change this if EMBEDDINGS_MODEL
            # is swapped for a model with a different output size.
            {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"},
            {"type": "filter", "path": "business_id"},
        ]
    },
}


def embed_text(text):
    """Trả về embedding vector (list[float]) cho `text`, hoặc None nếu chưa cấu hình
    EMBEDDINGS_API_KEY hoặc gọi API lỗi. Luôn best-effort, không bao giờ raise ra ngoài."""
    api_key = os.environ.get('EMBEDDINGS_API_KEY')
    if not api_key or not text or not text.strip():
        return None
    try:
        resp = requests.post(
            EMBEDDINGS_API_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={"model": EMBEDDINGS_MODEL, "input": text[:8000]},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['data'][0]['embedding']
    except Exception:
        return None


def ensure_vector_index():
    """Best-effort tạo Atlas Vector Search index nếu chưa có — an toàn để gọi nhiều lần
    (bỏ qua nếu index đã tồn tại). Một số cluster tier (free/shared M0/M2/M5) KHÔNG hỗ
    trợ Vector Search; khi đó hàm này lỗi êm và trả về False — cần nâng cấp tier hoặc
    tạo thủ công qua Atlas UI trên cluster có hỗ trợ."""
    if MONGO_STATUS != "CONNECTED":
        return False
    try:
        existing = list(db.business_knowledge.list_search_indexes())
        if any(idx.get('name') == VECTOR_INDEX_NAME for idx in existing):
            return True
        db.business_knowledge.create_search_index(VECTOR_INDEX_DEFINITION)
        return True
    except Exception as e:
        print(f"[ensure_vector_index] Không tự tạo được Atlas Vector Search index (cluster tier có thể chưa hỗ trợ, hoặc index đã tồn tại): {str(e)}")
        return False


def reindex_business_knowledge(business_id):
    """Sinh embedding cho toàn bộ sản phẩm/dịch vụ ĐANG BÁN của 1 tenant và upsert vào
    business_knowledge. Gọi lại hàm này mỗi khi tenant thêm/sửa sản phẩm đáng kể (thủ
    công qua route /api/ai/reindex_knowledge lúc này — chưa có trigger tự động). Trả về
    số lượng entry đã reindex thành công."""
    if MONGO_STATUS != "CONNECTED" or not business_id:
        return 0
    try:
        products = list(db.products.find(
            {'business_id': business_id, 'is_active': 1},
            {'id': 1, 'name': 1, 'category': 1, 'price': 1, '_id': 0}
        ))
    except Exception:
        return 0

    count = 0
    for p in products:
        text = f"{p.get('name')} ({p.get('category') or 'khác'}): {int(p.get('price') or 0):,}đ".replace(',', '.')
        vector = embed_text(text)
        if vector is None:
            continue
        try:
            db.business_knowledge.update_one(
                {'business_id': business_id, 'source_type': 'product', 'source_id': p.get('id')},
                {'$set': {
                    'business_id': business_id, 'source_type': 'product', 'source_id': p.get('id'),
                    'text': text, 'embedding': vector,
                }},
                upsert=True,
            )
            count += 1
        except Exception:
            continue
    return count


def retrieve_relevant_knowledge(business_id, query_text, top_k=5):
    """Semantic retrieval: trả về list[str] các đoạn kiến thức LIÊN QUAN NHẤT tới đúng
    câu hỏi hiện tại của khách, thay vì nhúng nguyên bảng giá mỗi lượt. Trả về [] nếu
    chưa cấu hình embeddings, tenant này chưa được reindex, hoặc index chưa sẵn sàng —
    luôn an toàn để gọi vô điều kiện, không bao giờ raise ra ngoài."""
    if MONGO_STATUS != "CONNECTED" or not business_id or not query_text:
        return []
    query_vector = embed_text(query_text)
    if query_vector is None:
        return []
    try:
        pipeline = [
            {"$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "filter": {"business_id": business_id},
                "numCandidates": max(top_k * 10, 50),
                "limit": top_k,
            }},
            {"$project": {"text": 1, "_id": 0}},
        ]
        results = list(db.business_knowledge.aggregate(pipeline))
        return [r['text'] for r in results if r.get('text')]
    except Exception:
        return []
