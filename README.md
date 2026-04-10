# Aetna Assignment — Movie Systems Design

## Demo

https://github.com/user-attachments/assets/acdb0141-daa7-40ca-be27-b72654e20138

**Live Website:** [http://movie-assistant-web.s3-website-us-east-1.amazonaws.com](http://movie-assistant-web.s3-website-us-east-1.amazonaws.com)

**Live API Endpoint:** `http://a623da9515ac547dfa84556caa73f711-1418076793.us-west-2.elb.amazonaws.com/ask`

---

## Repository Structure

```
Aetna_Assignment/
├── db/                        # SQLite databases (original + processed)
├── movie-deploy/              # Deployment files (Dockerfile, k8s manifests)
├── Data_Prep.ipynb            # Step 1: Data preprocessing & sampling
├── Data_Enrich.ipynb          # Step 2: LLM-based data enrichment
├── Model_Build.ipynb          # Step 3: System design, evaluation & iteration
├── index.html                 # Frontend UI
├── eval_dataset.json          # Auto-generated evaluation test cases
├── eval_results.json          # Model grading results
├── .gitignore
├── LICENSE
└── README.md
```

---

## Step 1: Data Preprocessing

[Data_Prep.ipynb](https://github.com/manojkolluri/Aetna_Assignment/blob/main/Data_Prep.ipynb)

I started by importing both datasets — `movies.db` (45,430 movies × 12 columns) and `ratings.db` (100,004 ratings × 5 columns). Since the task only required a sample of 50–100 movies, I decided early on that the best strategy was aggressive noise elimination rather than backfilling. With 45K records to work with, I had more than enough headroom to drop anything imperfect and still end up with a clean, high-quality sample.

### Cleaning the Movies Table

The first thing I did was check for nulls across all columns. Everything came back clean except the `language` column, which had 45,430 nulls — every single row. The entire column was empty, so I dropped it immediately.

But nulls only tell part of the story. When I inspected the duplicate `imdbId` values, I noticed they weren't actually duplicates — they were empty strings that passed the null check. This prompted me to look deeper. I found empty strings hiding in `imdbId`, `overview`, and `releaseDate`. I found empty JSON arrays `[]` in `productionCompanies` and `genres`. And I found zeros in `budget` and `revenue` that weren't real zeros — they were missing data disguised as zeros. A movie with a budget of $0 and revenue of $0 isn't a real data point; it's noise.

I went column by column and removed every record that had any of these issues:

| Column | Issue | Removed | Remaining |
|--------|-------|---------|-----------|
| `language` | 45,430 nulls | Dropped column | 45,430 |
| `imdbId` | 17 empty strings | 17 | 45,413 |
| `budget` | 36,535 zeros | 36,535 | 8,878 |
| `revenue` | 3,503 zeros | 3,503 | 5,375 |
| `overview` | 11 empty strings | 11 | 5,364 |
| `productionCompanies` | 177 empty `[]` | 177 | 5,187 |
| `runtime` | 0 issues | 0 | 5,187 |
| `genres` | 1 empty `[]` | 1 | 5,186 |
| `status` | 2 non-Released | 2 | **5,184** |

The biggest drop came from removing zero-budget movies (36,535 records). In a production environment, I would have built a backfilling strategy — perhaps using external APIs like TMDb to fetch missing budgets, or training a regression model to estimate them from genre, year, and production company. But for a 100-movie sample, elimination was the right call.

I also removed 2 movies with a status of "Rumored" and "Post Production" since they weren't actually released films.

### Cleaning the Ratings Table

The ratings data was cleaner from the start — 100,004 ratings from 671 unique users across 9,066 unique movies. No nulls, no duplicates, rating range 0.5–5.0 with an average of 3.54.

However, there was still a risk of outliers skewing the sample. Some movies had an unusually high number of ratings while others had very few. I used a normal distribution analysis to identify movies at the extreme ends of the rating count spectrum and removed them. After filtering, the remaining ratings represented approximately **8,370 unique movies** within a statistically normal band.

### Building the Final Sample

With both datasets cleaned, I needed to find the intersection — movies that had both complete metadata AND normal rating distributions. I checked the overlap between my cleaned movies (5,184) and the normal-band rated movies (8,370). The result was **841 movies** that met both criteria.

From these 841, I took a random sample of **100 movies** using `random_state=42` for reproducibility.

For each of the 100 movies, I then computed three additional columns from the ratings data:
- `avg_rating` — the mean rating across all users who rated that movie
- `rating_count` — total number of ratings
- `user_ratings` — a JSON array containing every individual `{userId, rating}` pair, which I knew I'd need later for user preference analysis

I stored the final dataset in `db/Final_movies.db` as the `Final_movies` table — 100 rows × 14 columns of clean, complete, ratings-enriched movie data ready for LLM enrichment.

---

## Step 2: LLM Data Enrichment

[Data_Enrich.ipynb](https://github.com/manojkolluri/Aetna_Assignment/blob/main/Data_Enrich.ipynb)

With the clean 100-movie dataset ready, I needed to generate 5 new attributes for each movie using an LLM. The attributes I chose were:

- **sentiment** — tone of the movie overview (positive / negative / neutral)
- **budget_tier** — low (<$10M), medium ($10M–$50M), high ($50M–$100M), blockbuster (>$100M)
- **revenue_tier** — flop (<$10M), average ($10M–$50M), hit ($50M–$100M), blockbuster (>$100M)
- **production_effectiveness_score** — a 0–100 composite score based on ROI (revenue/budget) and avg_rating. High ROI + high rating = 90–100, low ROI + low rating = 0–20.
- **audience_appeal** — inferred target audience based on overview and genres (family / teen / adult / general)

### The Design Challenge

I needed the LLM to produce structured, consistent output for all 100 movies. Three problems to solve:

1. **Consistency** — the model had to return the exact same schema every time, no variation in field names or formats.
2. **Scale** — calling the API 100 times individually would be slow and expensive. But sending all 100 movies in a single prompt risked hitting token limits and degraded output quality.
3. **Reliability** — the model might sometimes respond in plain text instead of structured data.

### My Solution: Forced Tool Calling

I solved all three problems with a single design decision: **forced tool call invocation**. Instead of asking the model to return JSON in a text response (which can be inconsistent), I defined a `movie_enrichment` tool schema and forced the model to always call it. This guaranteed structured output with typed fields and enum constraints every time.

The tool schema I defined had strict types — `sentiment` was constrained to `["positive", "negative", "neutral"]`, `budget_tier` to `["low", "medium", "high", "blockbuster"]`, and so on. The model couldn't deviate because the tool schema enforced it.

I set `tool_choice="movie_enrichment"` (not `"auto"`) which forced Claude to always invoke the tool rather than responding with plain text. Combined with `temperature=0.0` for deterministic output, this gave me completely consistent enrichment across all 100 movies.

### Batch Processing

I split the 100 movies into batches of 10 and processed them sequentially — 10 batches total. For each batch, I formatted the movie data inside XML tags (`<movie_data>...</movie_data>`) with a clear, direct prompt:

```
You are a movie data analyst. Analyze the movies below and enrich each one with 5 attributes.

Guidelines:
- sentiment: Analyze the overview tone (positive/negative/neutral)
- budget_tier: low (<$10M), medium ($10M-$50M), high ($50M-$100M), blockbuster (>$100M)
- revenue_tier: flop (<$10M), average ($10M-$50M), hit ($50M-$100M), blockbuster (>$100M)
- production_effectiveness_score: 0-100 score. Consider ROI and avg_rating together.
- audience_appeal: Based on overview and genres (family/teen/adult/general)

<movie_data>
  Movie ID: 2022
  Title: Mr. Deeds
  Overview: When Longfellow Deeds...
  Budget: $50,000,000
  Revenue: $171,269,535
  Avg Rating: 3.42 / 5.0
  Genres: Comedy, Romance
  ---
  ... (9 more movies)
</movie_data>

Analyse all 10 movies and call the movie_enrichment tool.
```

The system prompt reinforced the tool-only behavior: *"You are a movie data analyst. Always call the movie_enrichment tool with your analysis. Never respond with plain text."*

I added a 1-second sleep between batches to avoid rate limiting.

### Results

All 10 batches processed successfully — 100/100 movies enriched with zero nulls across all 5 new columns. The enriched data (100 rows × 6 columns: movieId + 5 new attributes) was merged back into the original dataset, creating a final table of 100 rows × 19 columns.

### Storage

I stored the enriched data in two places:
1. **SQLite** (`db/enriched_movies.db`) — for local reference and notebook access
2. **Supabase (PostgreSQL)** — uploaded in batches of 10 via REST API, so the data would be easily accessible when I deployed the application later. This was a deliberate decision: I knew I'd be building an API that needed to query this data from a container, and a cloud-hosted database made that seamless without bundling SQLite files into Docker images.

---

## Step 3: Movie System Design, Evaluation & Iteration

[Model_Build.ipynb](https://github.com/manojkolluri/Aetna_Assignment/blob/main/Model_Build.ipynb)

### Building the System

I used Claude Sonnet 4 via Bedrock as the LLM and connected to the enriched movie data I had stored in Supabase in the previous step. The core design question was: how do I let the model intelligently query a database without writing raw SQL?

I created a single tool — `query_table` — that lets the model query the `enriched_movies` table with typed parameters: filters (key-value pairs), limit, order_by, and sort direction. The tool schema description lists every available column and its possible values, so the model knows exactly what data exists and how to filter it.

I then built an agentic conversation loop (`run_conversation`) that lets the model keep calling tools and reasoning in a loop until it has gathered enough information to produce a final answer. For a comparison query, the model might make 2-3 tool calls (one per movie). For recommendations, it makes 1-2 calls with different filters. The loop runs until the model's stop reason is no longer `tool_use` — meaning it's ready to respond.

### The Initial System Prompt (V1)

I wrote a straightforward system prompt that defined three tasks: recommendations, user preference summaries, and comparative analysis. Each section described the expected behavior — use filters, rank by score, compare across metrics, etc. Basic guidelines included "always query the database before answering" and "be concise and structured."

I tested it with a simple query — "Summarize preferences for userId 23" — and the output looked reasonable to my eyes. But I didn't want to rely on human judgment alone. I wanted to verify the model's accuracy systematically.

### Building the Evaluation Pipeline

I needed three things: a dataset to test against, a way to run the model on that dataset, and a way to grade the results.

**Generating the evaluation dataset:** I wrote a function that feeds the complete data snapshot (all 100 movies with key attributes) to Claude and asks it to generate 10 test cases — 3 recommendations, 3 user preferences, 4 comparisons. The critical constraint: the model could only use real titles, real userIds, and real filter values from the snapshot. This prevented evaluating against hallucinated ground truth.

For this generation step, I deliberately did not use tool calling. Instead, I used a different structured extraction technique — **stop sequences with assistant message prefilling**. I prefilled the assistant's response with `` ```json `` and set the stop sequence to `` ``` ``. This forced the model to output only valid JSON between the code fences, with no preamble or explanation. I also set `temperature=1.0` so the generated test cases would be diverse and challenging rather than predictable.

**Model-based grading:** I created a grading function where a separate Claude instance evaluates the main model's output. The grader receives the original query, the model's response, the evaluation criteria, and the complete data snapshot. It scores each response 1–10 with structured feedback: strengths, weaknesses, and reasoning. The grader also uses the stop sequence + prefilling technique for consistent JSON output.

The scoring guide I defined:
- 9–10: Fully addresses query, accurate data, well structured
- 7–8: Mostly correct, minor gaps
- 5–6: Partially correct, missing key elements
- 1–4: Incorrect, hallucinated data, or missed the query type

### V1 Evaluation Results

| Query Type | Avg Score | Key Issues |
|-----------|----------|------------|
| Recommendation | 6.7/10 | Genre mismatches — recommending "Thriller" for "Action" queries |
| User Preference | 5.0/10 | Fabricated entire user rating profiles with non-existent data |
| Comparison | 5.2/10 | Hallucinated specific dollar amounts and ROI calculations |
| **Overall** | **5.6/10** | |

The results were eye-opening. The model was hallucinating heavily — inventing specific budget figures like "$4M" when the database only stores tier labels like "low." It was fabricating user ratings for movies that users never rated. And it was including adjacent genres (Thriller for Action) in recommendations.

### Improving the System Prompt (V2)

Based on the evaluation feedback, I made three targeted improvements:

**1. Anti-hallucination grounding rules:** I added explicit constraints like "NEVER invent or estimate specific dollar amounts for budget or revenue. The database only stores tiers — use those exact labels" and "NEVER calculate ROI, return multiples, or revenue/budget ratios — this data is not available." I also added "Stick strictly to what the database returns — do not supplement with outside knowledge."

**2. Chain-of-thought for user preferences:** The biggest failure was in user preference summaries. The model was confusing `avg_rating` (the global average) with individual user ratings, and fabricating ratings for users who hadn't rated certain movies. I replaced the vague instructions with explicit step-by-step directions:
- Step 1: Fetch ALL movies (limit=100)
- Step 2: Parse the `user_ratings` JSON for the specific userId
- Step 3: Collect only movies this user actually rated
- Step 4: Split into liked (≥4.0), disliked (≤2.0), neutral
- Step 5: Summarize patterns

This chain-of-thought approach forced the model to follow a deterministic process rather than guessing.

**3. Strict genre rule:** I added "If the user asks for a specific genre (e.g. 'action'), only recommend movies whose genres field explicitly contains that genre word. Do NOT include movies that are adjacent (e.g. Thriller is not Action)."

### V2 Evaluation Results

| Query Type | V1 Score | V2 Score | Improvement |
|-----------|---------|---------|-------------|
| Recommendation | 6.7/10 | 7.0/10 | +0.3 |
| User Preference | 5.0/10 | 6.0/10 | +1.0 |
| Comparison | 5.2/10 | 8.5/10 | **+3.3** |
| **Overall** | **5.6/10** | **7.3/10** | **+1.7** |

The biggest improvement was in comparisons — from 5.2 to 8.5. The grounding rules eliminated the hallucinated financial figures entirely. User preferences improved but remained the hardest task due to the complexity of parsing nested JSON ratings. Recommendations improved slightly with stricter genre matching.

I finalized the V2 system prompt, tool schema, and conversation loop for production deployment.

---
---

## Step 4: Deployment

[movie-deploy/](https://github.com/manojkolluri/Aetna_Assignment/tree/main/movie-deploy)


### Architecture

```
Frontend (S3)  →  EKS LoadBalancer  →  2 Flask Pods  →  Bedrock (Claude)
                                                     →  Supabase (Data)
```

### Containerization

I wrapped the finalized model, tool, and system prompt into a Flask API with two endpoints: `/health` for Kubernetes probes and `/ask` for queries. I used Gunicorn as the production server with a 120-second timeout (LLM calls can take 30–60 seconds) and 2 workers.

I packaged everything in a Docker image using `python:3.11-slim` as the base and built with `--platform linux/amd64` since my Mac uses ARM but EKS nodes run x86.

### Kubernetes (EKS)

I deployed the image to an EKS cluster with 2 `t3.medium` worker nodes. The deployment runs 2 pod replicas behind an AWS LoadBalancer for fault tolerance and load distribution. I configured liveness and readiness probes on the `/health` endpoint to ensure automatic recovery if a pod crashes. Sensitive configuration (the Supabase key) is stored as a Kubernetes Secret rather than hardcoded.

I attached IAM policies to the node role for Bedrock access (LLM calls) and ECR access (pulling the Docker image).

### Frontend

I built a simple HTML/CSS/JS frontend and hosted it on S3 as a static website. It calls the EKS API endpoint, renders responses as formatted Markdown, and includes pre-built example queries from the highest-scoring evaluation results. I added `flask-cors` to the API to handle cross-origin requests between the S3 domain and EKS domain.

### Deployment Flow

```
1. docker build --platform linux/amd64     →  Local image
2. docker push to ECR                      →  Image in AWS registry
3. eksctl create cluster                   →  EKS cluster (2 nodes)
4. Attach IAM policies                     →  Bedrock + ECR access
5. kubectl create secret                   →  Supabase credentials
6. kubectl apply deployment + service      →  Pods running + LoadBalancer
7. aws s3 cp index.html                    →  Frontend live on S3
```

---

## Key Design Decisions

**Forced tool calling for enrichment vs auto tool calling for queries:** During data enrichment (Step 2), I forced the model to always call the `movie_enrichment` tool to guarantee structured output. During the query system (Step 3), I used `auto` tool choice so the model could decide when and how many times to query the database. Different tasks require different levels of autonomy.

**Stop sequences + prefilling vs tool calling for evaluation:** For generating the eval dataset and grading responses, I used stop sequences with assistant message prefilling instead of tool calling. This was a deliberate choice — these tasks needed free-form JSON output with variable structure, which is better suited to stop-sequence extraction than rigid tool schemas.

**Supabase REST API over SQLite in production:** The assignment provided SQLite, but containers are ephemeral — bundling a database file into a Docker image is fragile. Supabase gave me a cloud-hosted PostgreSQL database accessible via REST API from anywhere, which made the transition from notebook to deployed API seamless.

**Single flexible tool vs multiple specialized tools:** I gave the model one `query_table` tool with flexible filters, ordering, and limits rather than separate tools for recommendations, comparisons, and preferences. This reduced tool schema complexity and let the model compose its own query patterns rather than being locked into predefined paths.

**Model-based evaluation over manual testing:** I could have manually tested 10 queries and eyeballed the results. Instead, I automated the entire evaluation pipeline — dataset generation, model execution, and grading — all powered by Claude. This made the process reproducible, scalable, and objective.

---

## Technologies Used

| Layer | Technology | Purpose |
|-------|-----------|---------|
| LLM | Claude Sonnet 4 via AWS Bedrock | Reasoning, enrichment, recommendations, grading |
| Database | Supabase (PostgreSQL) | Movie data storage and REST API |
| Compute | Amazon SageMaker | Notebook development and testing |
| Backend | Flask + Gunicorn | REST API serving |
| Container | Docker + AWS ECR | Image packaging and registry |
| Orchestration | AWS EKS (Kubernetes) | Container deployment with scaling |
| Frontend | HTML/CSS/JS + AWS S3 | Static website hosting |
| IAM | AWS IAM | Permissions for Bedrock and ECR |
