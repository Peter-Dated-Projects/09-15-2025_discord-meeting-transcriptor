import asyncio
import os
import sys

# Add source to path
sys.path.append(os.getcwd())

from source.server.common.chroma import ChromaDBClient


async def check_chroma():
    client = ChromaDBClient(host="localhost", port=8000)
    await client.connect()

    try:
        if await client.collection_exists("summaries"):
            collection = client.client.get_collection("summaries")
            count = collection.count()
            print(f"Collection 'summaries' has {count} items.")

            if count > 0:
                peek = collection.peek(limit=1)
                print("Sample item:", peek)
        else:
            print("Collection 'summaries' does not exist.")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(check_chroma())
