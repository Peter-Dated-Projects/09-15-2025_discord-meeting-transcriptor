# Static collections that are pre-initialized
DEFAULT_VECTORDB_COLLECTIONS = ["summaries"]

# Dynamic collections (created on-demand):
# - embeddings_{guild_id}: Text embeddings for meeting segments, created per-guild
#   to isolate RAG contexts. These are created dynamically when embedding jobs run
#   and do not need pre-initialization.
