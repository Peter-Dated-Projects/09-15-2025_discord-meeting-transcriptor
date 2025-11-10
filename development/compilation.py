# This is the main entry point for random local development work
# Specifically for things like:
# - testing out new integrations
# - experimenting with new features

import torch

print(torch.version.cuda)  # '12.8'
print(torch.cuda.is_available())  # True
print(torch.cuda.get_device_name(0))  # should show your RTX 50xx


import chromadb


# ephemeral client for local development
client = chromadb.Client()
print("Created ChromaDB client:", client)

from sentence_transformers import SentenceTransformer
from chromadb.utils.embedding_functions import EmbeddingFunction


class EF(EmbeddingFunction):
    def __init__(self):
        self.m = SentenceTransformer("BAAI/bge-small-en-v1.5")

    def __call__(self, texts):
        return self.m.encode(texts, normalize_embeddings=True).tolist()


ef = EF()
coll = client.get_or_create_collection("meeting_chunks", embedding_function=ef)
