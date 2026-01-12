# tools/serpapi.py
import os
import requests
from azure.ai.agents.models import FunctionToolDefinition

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

def serpapi_search(query: str, location: str = "India", num_results: int = 5):
    url = "https://serpapi.com/search"

    params = {
        "q": query,
        "engine": "google",
        "location": location,
        "num": num_results,
        "api_key": SERPAPI_API_KEY
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    results = []
    for item in data.get("organic_results", []):
        results.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet")
        })

    return results


# ✅ THIS IS THE KEY FIX
serpapi_tool = FunctionToolDefinition(
    function={
        "name": "serpapi_search",
        "description": "Search Google via SerpAPI for latest real-world information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "location": {
                    "type": "string",
                    "description": "Geographic location"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of search results",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
)
