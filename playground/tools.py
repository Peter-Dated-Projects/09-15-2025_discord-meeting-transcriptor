from dotenv import load_dotenv

load_dotenv(".env.local")


from googleapiclient.discovery import build


def google_search(query, api_key, cse_id, **kwargs):
    """
    Performs a Google search using the Custom Search JSON API.

    Args:
        query (str): The search term.
        api_key (str): Your Google Cloud API Key.
        cse_id (str): Your Programmable Search Engine ID (cx).
        **kwargs: Additional arguments (e.g., num=10, gl='us').
    """
    service = build("customsearch", "v1", developerKey=api_key, cache_discovery=False)

    # Execute the search
    res = service.cse().list(q=query, cx=cse_id, **kwargs).execute()

    # Extract results
    return res.get("items", [])


# --- Configuration ---
import os

MY_API_KEY = os.getenv("GCP_CUSTOM_SEARCH_API_KEY")
MY_CSE_ID = os.getenv("GCP_PROGRAMMABLE_SEARCH_ENGINE_CX")

print("Google API Key:", MY_API_KEY)
print("Google CSE ID:", MY_CSE_ID)

# --- Main Execution ---
if __name__ == "__main__":
    search_term = "latest python trends 2025"

    try:
        results = google_search(search_term, MY_API_KEY, MY_CSE_ID, num=5, lr="lang_en")

        for i, result in enumerate(results, start=1):
            # these 3 args are the most relevant
            title = result.get("title")
            link = result.get("link")
            snippet = result.get("snippet")

            print(f"{i}. {result['title']}")
            print(f"   Link: {result['link']}")
            print(f"   Snippet: {result['snippet']}\n")

    except Exception as e:
        print(f"An error occurred: {e}")
