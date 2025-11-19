"""
ChromaDB Admin Dashboard

A simple Flask-based web interface to view ChromaDB collections and their contents.
Runs on localhost:3002
"""

import json
import os
from typing import Any

import chromadb
from flask import Flask, render_template_string, request

app = Flask(__name__)

# ChromaDB Configuration
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8000"))

# Global client
chroma_client = None


def get_client():
    """Get or create ChromaDB client."""
    global chroma_client
    if chroma_client is None:
        chroma_client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    return chroma_client


# HTML Templates
INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChromaDB Admin Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            overflow: hidden;
        }
        
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
        }
        
        .subtitle {
            opacity: 0.9;
            font-size: 1.1rem;
        }
        
        .content {
            padding: 30px;
        }
        
        .stats {
            display: flex;
            justify-content: space-around;
            margin-bottom: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .stat-box {
            text-align: center;
        }
        
        .stat-value {
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #6c757d;
            margin-top: 5px;
        }
        
        .collections-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }
        
        .collection-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
            text-decoration: none;
            color: inherit;
            display: block;
        }
        
        .collection-card:hover {
            border-color: #667eea;
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.2);
        }
        
        .collection-name {
            font-size: 1.3rem;
            font-weight: 600;
            color: #333;
            margin-bottom: 10px;
        }
        
        .collection-count {
            color: #6c757d;
            font-size: 0.95rem;
        }
        
        .collection-meta {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #e9ecef;
            font-size: 0.85rem;
            color: #6c757d;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #f5c6cb;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #6c757d;
        }
        
        .empty-state svg {
            width: 100px;
            height: 100px;
            margin-bottom: 20px;
            opacity: 0.3;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🗄️ ChromaDB Dashboard</h1>
            <div class="subtitle">Connected to {{ host }}:{{ port }}</div>
        </header>
        
        <div class="content">
            {% if error %}
                <div class="error">
                    <strong>Error:</strong> {{ error }}
                </div>
            {% else %}
                <div class="stats">
                    <div class="stat-box">
                        <div class="stat-value">{{ collections|length }}</div>
                        <div class="stat-label">Total Collections</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{{ total_documents }}</div>
                        <div class="stat-label">Total Documents</div>
                    </div>
                </div>
                
                {% if collections %}
                    <div class="collections-list">
                        {% for collection in collections %}
                            <a href="/collection/{{ collection.name }}" class="collection-card">
                                <div class="collection-name">{{ collection.name }}</div>
                                <div class="collection-count">
                                    📄 {{ collection.count }} documents
                                </div>
                                <div class="collection-meta">
                                    ID: {{ collection.id[:16] }}...
                                </div>
                            </a>
                        {% endfor %}
                    </div>
                {% else %}
                    <div class="empty-state">
                        <svg fill="currentColor" viewBox="0 0 20 20">
                            <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z"/>
                        </svg>
                        <h2>No Collections Found</h2>
                        <p>Create your first collection to get started.</p>
                    </div>
                {% endif %}
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

COLLECTION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ collection_name }} - ChromaDB Admin</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            overflow: hidden;
        }
        
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
        }
        
        .back-link {
            color: white;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            margin-bottom: 15px;
            opacity: 0.9;
            transition: opacity 0.3s;
        }
        
        .back-link:hover {
            opacity: 1;
        }
        
        h1 {
            font-size: 2rem;
            margin-bottom: 10px;
        }
        
        .subtitle {
            opacity: 0.9;
        }
        
        .content {
            padding: 30px;
        }
        
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .stat-box {
            flex: 1;
            text-align: center;
        }
        
        .stat-value {
            font-size: 1.5rem;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #6c757d;
            margin-top: 5px;
            font-size: 0.9rem;
        }
        
        .search-box {
            margin-bottom: 20px;
        }
        
        .search-box input {
            width: 100%;
            padding: 12px 20px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .documents-list {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .document-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        
        .document-card:hover {
            border-color: #667eea;
            box-shadow: 0 3px 10px rgba(102, 126, 234, 0.1);
        }
        
        .document-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e9ecef;
        }
        
        .document-id {
            font-family: monospace;
            color: #667eea;
            font-weight: 600;
            font-size: 0.9rem;
        }
        
        .document-distance {
            background: #e9ecef;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 0.85rem;
            color: #6c757d;
        }
        
        .document-content {
            margin-bottom: 15px;
            line-height: 1.6;
            color: #333;
        }
        
        .document-metadata {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            font-size: 0.9rem;
        }
        
        .metadata-title {
            font-weight: 600;
            color: #495057;
            margin-bottom: 10px;
        }
        
        .metadata-item {
            display: flex;
            padding: 5px 0;
            border-bottom: 1px solid #e9ecef;
        }
        
        .metadata-item:last-child {
            border-bottom: none;
        }
        
        .metadata-key {
            font-weight: 600;
            color: #6c757d;
            min-width: 150px;
        }
        
        .metadata-value {
            color: #495057;
            word-break: break-word;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #f5c6cb;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #6c757d;
        }
        
        pre {
            background: #f8f9fa;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <a href="/" class="back-link">← Back to Collections</a>
            <h1>📄 {{ collection_name }}</h1>
            <div class="subtitle">Collection Details</div>
        </header>
        
        <div class="content">
            {% if error %}
                <div class="error">
                    <strong>Error:</strong> {{ error }}
                </div>
            {% else %}
                <div class="stats">
                    <div class="stat-box">
                        <div class="stat-value">{{ document_count }}</div>
                        <div class="stat-label">Total Documents</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{{ metadata_fields|length }}</div>
                        <div class="stat-label">Metadata Fields</div>
                    </div>
                </div>
                
                {% if documents %}
                    <div class="documents-list">
                        {% for doc in documents %}
                            <div class="document-card">
                                <div class="document-header">
                                    <div class="document-id">ID: {{ doc.id }}</div>
                                    {% if doc.distance %}
                                        <div class="document-distance">Distance: {{ "%.4f"|format(doc.distance) }}</div>
                                    {% endif %}
                                </div>
                                
                                {% if doc.document %}
                                    <div class="document-content">
                                        <strong>Content:</strong><br>
                                        {{ doc.document[:500] }}{% if doc.document|length > 500 %}...{% endif %}
                                    </div>
                                {% endif %}
                                
                                {% if doc.metadata %}
                                    <div class="document-metadata">
                                        <div class="metadata-title">📋 Metadata</div>
                                        {% for key, value in doc.metadata.items() %}
                                            <div class="metadata-item">
                                                <div class="metadata-key">{{ key }}:</div>
                                                <div class="metadata-value">{{ value }}</div>
                                            </div>
                                        {% endfor %}
                                    </div>
                                {% endif %}
                                
                                {% if doc.embedding %}
                                    <details style="margin-top: 15px;">
                                        <summary style="cursor: pointer; color: #667eea; font-weight: 600;">
                                            View Embedding ({{ doc.embedding|length }} dimensions)
                                        </summary>
                                        <pre>{{ doc.embedding[:10] }}... (truncated)</pre>
                                    </details>
                                {% endif %}
                            </div>
                        {% endfor %}
                    </div>
                {% else %}
                    <div class="empty-state">
                        <h2>No Documents Found</h2>
                        <p>This collection is empty.</p>
                    </div>
                {% endif %}
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    """Display all collections."""
    try:
        client = get_client()
        collections = client.list_collections()

        collection_data = []
        total_documents = 0

        for collection in collections:
            count = collection.count()
            total_documents += count
            collection_data.append(
                {"name": collection.name, "id": str(collection.id), "count": count}
            )

        # Sort by name
        collection_data.sort(key=lambda x: x["name"])

        return render_template_string(
            INDEX_TEMPLATE,
            collections=collection_data,
            total_documents=total_documents,
            host=CHROMADB_HOST,
            port=CHROMADB_PORT,
            error=None,
        )
    except Exception as e:
        return render_template_string(
            INDEX_TEMPLATE,
            collections=[],
            total_documents=0,
            host=CHROMADB_HOST,
            port=CHROMADB_PORT,
            error=str(e),
        )


@app.route("/collection/<collection_name>")
def view_collection(collection_name):
    """Display all documents in a collection."""
    try:
        client = get_client()
        collection = client.get_collection(name=collection_name)

        # Get all documents
        results = collection.get(include=["documents", "metadatas", "embeddings"])

        documents = []
        metadata_fields = set()

        if results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                doc_data: dict[str, Any] = {"id": doc_id}

                if results.get("documents") and i < len(results["documents"]):
                    doc_data["document"] = results["documents"][i]

                if results.get("metadatas") and i < len(results["metadatas"]):
                    metadata = results["metadatas"][i]
                    doc_data["metadata"] = metadata
                    if metadata:
                        metadata_fields.update(metadata.keys())

                if results.get("embeddings") and i < len(results["embeddings"]):
                    doc_data["embedding"] = results["embeddings"][i]

                if results.get("distances") and i < len(results["distances"]):
                    doc_data["distance"] = results["distances"][i]

                documents.append(doc_data)

        return render_template_string(
            COLLECTION_TEMPLATE,
            collection_name=collection_name,
            documents=documents,
            document_count=len(documents),
            metadata_fields=sorted(metadata_fields),
            error=None,
        )
    except Exception as e:
        return render_template_string(
            COLLECTION_TEMPLATE,
            collection_name=collection_name,
            documents=[],
            document_count=0,
            metadata_fields=[],
            error=str(e),
        )


@app.route("/health")
def health():
    """Health check endpoint."""
    try:
        client = get_client()
        client.heartbeat()
        return {"status": "ok", "message": "ChromaDB connection healthy"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


if __name__ == "__main__":
    print("=" * 60)
    print("🗄️  ChromaDB Admin Dashboard")
    print("=" * 60)
    print(f"📡 ChromaDB Server: {CHROMADB_HOST}:{CHROMADB_PORT}")
    print(f"🌐 Dashboard URL: http://localhost:3002")
    print("=" * 60)
    print()

    app.run(host="0.0.0.0", port=3002, debug=True)
