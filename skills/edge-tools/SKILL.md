---
name: edge-tools
description: Comprehensive suite of tactical multimodal tools recursed from edge-Ai (embeddings, semantic retrieval, context caching, grounding, and code utilities).
---

# ⚡ edge Tactical Tools Suite

## 🎯 Overview
Recursed directly from the core `edge-tools.py` engine. Provides advanced multimodal tool functions, vector embeddings, context caching, and semantic search utilities.

---

## 🛠️ Key Tool Functions Available

1. **Embeddings & Vector Processing**:
   * `get_embedding(text, model, task_type)`: Generates dense text embeddings for similarity matching.
   * `batch_get_embeddings(texts, model, task_type)`: Efficient multi-vector embedding generation.
2. **Context Caching**:
   * `create_edge-cache(content, model, ttl_minutes)`: Creates TTL-managed cached prompts for high-token system prompt efficiency.
3. **Semantic Retrieval & File Search**:
   * `create_edge-search_store(display_name)`: Sets up a managed semantic retriever corpus.
   * `upload_knowledge_to_store(file_path, store_name)`: Indexes local documents into semantic stores.
   * `query_edge-knowledge(query, store_name)`: Queries indexed corpora with citation grounding.
4. **Autonomous Utilities**:
   * `get_current_time()`: Safe UTC timestamp formatting.
   * `safe_print(msg)`: Unicode-safe terminal output avoiding Windows encoding traps.

---

## 🚀 Usage in NouGenCode
```python
from skills.edge-tools.scripts.edge-tools import (
    get_embedding,
    batch_get_embeddings,
    create_edge-cache,
    query_edge-knowledge,
)
```
