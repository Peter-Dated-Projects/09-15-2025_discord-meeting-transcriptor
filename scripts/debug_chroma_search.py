import asyncio
import os
import sys

# Add source to path
sys.path.append(os.getcwd())

from source.server.common.chroma import ChromaDBClient
from source.services.transcription.text_embedding_manager.manager import EmbeddingModelHandler
from source.services.chat.mcp.tools.chroma_search_tool import query_chroma_summaries


async def debug_search():
    # 1. Connect to Chroma
    client = ChromaDBClient(host="localhost", port=8000)
    await client.connect()

    if not await client.collection_exists("summaries"):
        print("Collection 'summaries' does not exist.")
        return

    collection = client.client.get_collection("summaries")
    count = collection.count()
    print(f"Collection 'summaries' has {count} items.")

    # Mock context with services
    class MockContext:
        def __init__(self):
            self.services_manager = MockServicesManager()

    class MockServicesManager:
        def __init__(self):
            self.server = MockServer()
            self.gpu_resource_manager = MockGPUManager()
            self.logging_service = MockLogger()

    class MockServer:
        def __init__(self):
            self.vector_db_client = client

    class MockGPUManager:
        def acquire_lock(self, job_type, job_id, metadata):
            return AsyncContextManager()

    class AsyncContextManager:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class MockLogger:
        async def error(self, msg):
            print(f"ERROR: {msg}")

    context = MockContext()

    queries = ["Finks", "paper trading", "onboarding"]
    print(f"\nRunning batch search for {len(queries)} queries...")

    try:
        # Call the tool with the LIST of queries
        result = await query_chroma_summaries(queries, context, n_results=2)

        if "error" in result:
            print(f"Search failed: {result['error']}")
        else:
            results = result["results"]
            print(f"Found {len(results)} results.")
            for res in results:
                print(
                    f"- [{res['distance']:.4f}] {res['meeting_id']} (Query: {res.get('query', 'unknown')})"
                )
                print(f"  Summary: {res['summary_text'][:100]}...")

    except Exception as e:
        print(f"Execution failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_search())
