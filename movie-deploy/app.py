from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
import requests
import json
import os

app = Flask(__name__)
CORS(app)
# ---------- Config ----------
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zqvjzukfbfcixxaplzyp.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_LHNy1oE6UxRZtndOBjPoVg_bRaz6_VG")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-4-20250514-v1:0")

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
sb_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# ---------- Core Query Function ----------
def query_table(filters, limit=10, order_by=None, ascending=False):
    url = f"{SUPABASE_URL}/rest/v1/enriched_movies"
    params = {"limit": limit}
    for col, val in filters.items():
        params[col] = f"eq.{val}"
    if order_by:
        direction = "asc" if ascending else "desc"
        params["order"] = f"{order_by}.{direction}"
    response = requests.get(url, headers=sb_headers, params=params)
    if response.status_code == 200:
        return response.json()
    return {"error": f"{response.status_code} - {response.text}"}

# ---------- LLM Helpers ----------
def add_user_message(messages, content):
    if isinstance(content, str):
        messages.append({"role": "user", "content": [{"text": content}]})
    else:
        messages.append({"role": "user", "content": content})

def add_assistant_message(messages, content):
    if isinstance(content, str):
        messages.append({"role": "assistant", "content": [{"text": content}]})
    else:
        messages.append({"role": "assistant", "content": content})

def chat(messages, system=None, temperature=0.0, tools=None):
    params = {
        "modelId": MODEL_ID,
        "messages": messages,
        "inferenceConfig": {"temperature": temperature},
    }
    if system:
        params["system"] = [{"text": system}]
    if tools:
        params["toolConfig"] = {"tools": tools, "toolChoice": {"auto": {}}}
    response = bedrock.converse(**params)
    parts = response["output"]["message"]["content"]
    return {
        "parts": parts,
        "stop_reason": response["stopReason"],
        "text": "\n".join([p["text"] for p in parts if "text" in p]),
    }

# ---------- Tool Schema ----------
query_table_schema = {
    "toolSpec": {
        "name": "query_table",
        "description": """Queries the enriched_movies table in Supabase.
        Use this to fetch movies based on filters for recommendations,
        comparisons, or user preference analysis.
        Available columns:
        - movieId, title, overview, genres, releaseDate, runtime
        - budget, revenue, budget_tier (low/medium/high/blockbuster)
        - revenue_tier (flop/average/hit/blockbuster)
        - avg_rating, rating_count, user_ratings (JSON list of userId + rating)
        - sentiment (positive/negative/neutral)
        - audience_appeal (family/teen/adult/general)
        - production_effectiveness_score (0-100)
        """,
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Key-value pairs to filter movies. Pass empty {} to retrieve all.",
                        "additionalProperties": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return. Default 10.",
                        "default": 10
                    },
                    "order_by": {
                        "type": "string",
                        "description": "Column to sort by. e.g. avg_rating, production_effectiveness_score"
                    },
                    "ascending": {
                        "type": "boolean",
                        "description": "Sort ascending if true. Default false.",
                        "default": False
                    }
                },
                "required": ["filters"]
            }
        }
    }
}

# ---------- Tool Execution ----------
def run_tool(tool_name, tool_input):
    if tool_name == "query_table":
        return query_table(
            filters=tool_input.get("filters", {}),
            limit=tool_input.get("limit", 10),
            order_by=tool_input.get("order_by", None),
            ascending=tool_input.get("ascending", False)
        )
    raise Exception(f"Unknown tool: {tool_name}")

def run_tools(parts):
    tool_results = []
    for part in parts:
        if "toolUse" not in part:
            continue
        tool_use_id = part["toolUse"]["toolUseId"]
        tool_name = part["toolUse"]["name"]
        tool_input = part["toolUse"]["input"]
        try:
            output = run_tool(tool_name, tool_input)
            tool_results.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": json.dumps(output)}],
                    "status": "success"
                }
            })
        except Exception as e:
            tool_results.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": f"Error: {e}"}],
                    "status": "error"
                }
            })
    return tool_results

# ---------- System Prompt (the improved one) ----------
SYSTEM_PROMPT = """You are an intelligent Movie Assistant with access to a curated database
of 100 enriched movies. You help users with three tasks:

## 1. Personalized Movie Recommendations
- Use query_table with relevant filters (sentiment, budget_tier, revenue_tier, audience_appeal)
- Rank by production_effectiveness_score or avg_rating
- Return top 5 movies with title, genres, avg_rating, and a reason for recommendation
- STRICT GENRE RULE: If the user asks for a specific genre (e.g. "action"),
  only recommend movies whose genres field explicitly contains that genre word.
  Do NOT include movies that are adjacent (e.g. Thriller is not Action).
- If fewer than 5 movies match all filters, reduce the number of recommendations
  rather than including movies that don't match.

## 2. User Preference Summary
When given a userId, follow these steps EXACTLY:
Step 1 - Fetch ALL movies from the database (use filters={}, limit=100)
Step 2 - For each movie, the user_ratings column is a JSON string like:
         '[{"userId": 23, "rating": 4.0}, {"userId": 45, "rating": 3.0}]'
         Search through each movie's user_ratings to find entries where userId matches.
Step 3 - Collect ALL movies this user has rated. For each, note:
         - title, genres, sentiment, budget_tier, audience_appeal
         - the specific rating this user gave (not avg_rating)
Step 4 - Split into:
         - Liked movies: rating >= 4.0
         - Disliked movies: rating <= 2.0
         - Neutral movies: rating between 2.0 and 4.0
Step 5 - Summarize preferences:
         - Favorite genres (most common in liked movies)
         - Preferred sentiment, budget_tier, audience_appeal
         - Average rating this user gives
         - 2-3 sentence personality profile of this user's taste
- If the userId has rated fewer than 3 movies, say so clearly.
- NEVER confuse avg_rating (the global average) with the user's personal rating.

## 3. Comparative Analysis
- Fetch each movie by title using query_table
- Compare ONLY using fields that exist in the database:
  budget_tier, revenue_tier, avg_rating, rating_count, production_effectiveness_score,
  sentiment, audience_appeal, genres
- NEVER invent or estimate specific dollar amounts for budget or revenue.
  The database only stores tiers (low/medium/high/blockbuster) - use those exact labels.
- NEVER calculate ROI, return multiples, or revenue/budget ratios.
- NEVER add release years or runtime minutes unless explicitly returned by query_table.
- Declare a winner per category and an overall winner based only on available data.

## Guidelines
- Always query the database before answering - never guess or invent movie details
- NEVER fabricate specific numbers not returned by query_table
- If a genre filter returns no results, tell the user clearly and suggest the closest alternative
- Always show avg_rating and production_effectiveness_score in your responses
- Stick strictly to what the database returns - do not supplement with outside knowledge
"""

# ---------- Conversation Loop ----------
def run_conversation(query):
    messages = []
    add_user_message(messages, query)
    tools = [query_table_schema]
    while True:
        result = chat(messages, system=SYSTEM_PROMPT, tools=tools)
        add_assistant_message(messages, result["parts"])
        if result["stop_reason"] != "tool_use":
            break
        tool_results = run_tools(result["parts"])
        add_user_message(messages, tool_results)
    return result["text"]

# ---------- API Endpoints ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})

@app.route("/ask", methods=["POST"])
def ask():
    data = request.json
    query = data.get("query")
    if not query:
        return jsonify({"error": "query is required"}), 400
    try:
        answer = run_conversation(query)
        return jsonify({"query": query, "answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
