# Aetna Assignment — Movie Systems Design

## Demo

https://github.com/user-attachments/assets/acdb0141-daa7-40ca-be27-b72654e20138

**Live Website:** [http://movie-assistant-web.s3-website-us-east-1.amazonaws.com](http://movie-assistant-web.s3-website-us-east-1.amazonaws.com)

**Live API Endpoint:** `http://a623da9515ac547dfa84556caa73f711-1418076793.us-west-2.elb.amazonaws.com/ask`

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Environment & Libraries](#environment--libraries)
4. [Task 1: Data Preparation & Enrichment](#task-1-data-preparation--enrichment)
5. [Task 2: Movie System Design](#task-2-movie-system-design)
6. [Prompt Engineering](#prompt-engineering)
7. [Model Evaluation](#model-evaluation)
8. [Deployment](#deployment)
9. [How to Run](#how-to-run)
10. [Repository Structure](#repository-structure)

---

## Overview

This project implements an end-to-end AI-powered Movie Assistant that enriches movie data using LLMs, builds an intelligent query system with tool calling, evaluates output quality using model-based grading, and deploys the entire application on AWS EKS (Kubernetes).

The system handles three types of queries:
- **Personalized Recommendations** — "Recommend action movies with positive sentiment"
- **User Preference Summaries** — "Summarize preferences for userId 23"
- **Comparative Analysis** — "Compare Dog Day Afternoon vs Heat on production effectiveness"

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│               Frontend (S3 Static Website)            │
│          HTML/CSS/JS with Markdown rendering          │
└─────────────────────────┬────────────────────────────┘
                          │ HTTP POST /ask
                          ▼
┌──────────────────────────────────────────────────────┐
│                  AWS EKS Cluster                      │
│         2 Pods (Flask + Gunicorn) behind              │
│              AWS LoadBalancer                          │
└──────────┬──────────────────────┬────────────────────┘
           │                      │
           ▼                      ▼
┌──────────────────┐   ┌──────────────────┐
│  AWS Bedrock     │   │   Supabase       │
│  Claude Sonnet 4 │   │   PostgreSQL     │
│  (LLM + Tools)   │   │   (enriched      │
│                  │   │    movie data)    │
└──────────────────┘   └──────────────────┘
```

**Data Flow:**
1. User submits a natural language query via the frontend
2. Request routes through EKS LoadBalancer to a Flask pod
3. Flask sends the query to Claude on Bedrock with a system prompt and tool schema
4. Claude autonomously decides what data it needs and makes tool calls to query Supabase
5. Tool results are returned to Claude, which may make additional calls if needed
6. Claude synthesizes a final structured response
7. Response is returned and rendered as formatted Markdown in the frontend

---

## Environment & Libraries

**Language:** Python 3.11

**Core Libraries:**
| Library | Purpose |
|---------|---------|
| `boto3` | AWS SDK — Bedrock (LLM) and S3 access |
| `requests` | HTTP client for Supabase REST API |
| `pandas` | Data manipulation during enrichment |
| `pdfplumber` | PDF text extraction (used in enrichment pipeline) |
| `flask` | REST API framework |
| `flask-cors` | Cross-origin support for frontend-backend communication |
| `gunicorn` | Production WSGI server |

**Why these choices:**
- **Supabase (PostgreSQL) over SQLite:** The assignment provided SQLite, but for deployment on Kubernetes, a cloud-hosted database is necessary since pods are ephemeral. Supabase provides a free PostgreSQL instance with a built-in REST API, eliminating the need for database drivers in the container.
- **Bedrock over direct API:** Serverless LLM access with IAM-based authentication. No API keys to manage in production. Native AWS integration with EKS.
- **Flask over FastAPI:** Simpler setup for a synchronous API. Gunicorn provides production-grade serving. The Bedrock calls are synchronous, so FastAPI's async advantage is minimal here.

---

## Task 1: Data Preparation & Enrichment

### Source Data
- **Movies table:** 45,430 movies with title, overview, genres, budget, revenue, runtime
- **Ratings table:** 100,004 user ratings with userId, movieId, rating, timestamp

### Enrichment Process

A sample of 100 movies was enriched using Claude (via Bedrock) to generate 5 additional attributes:

#### 1. Sentiment Analysis (`sentiment`)
LLM analyzed each movie's overview text and classified it as **positive**, **negative**, or **neutral**.

**Prompt approach:** Sent the overview text with instructions to classify based on tone, themes, and emotional content.

#### 2. Budget Tier (`budget_tier`)
Categorized production budgets into **low** / **medium** / **high** / **blockbuster** tiers.

**Prompt approach:** Provided budget ranges and asked the LLM to classify based on industry standards relative to release year.

#### 3. Revenue Tier (`revenue_tier`)
Categorized box office revenue into **flop** / **average** / **hit** / **blockbuster** tiers.

**Prompt approach:** Similar to budget tier, with revenue thresholds adjusted for era and inflation context.

#### 4. Audience Appeal (`audience_appeal`)
Classified target audience as **family** / **teen** / **adult** / **general** based on genres, overview, and content themes.

**Prompt approach:** LLM analyzed genre combinations and overview themes to infer the most likely target demographic.

#### 5. Production Effectiveness Score (`production_effectiveness_score`)
A 0-100 score combining budget efficiency, revenue performance, and audience ratings.

**Prompt approach:** LLM was given budget, revenue, and average rating data and asked to compute a composite effectiveness score with reasoning.

### Additional Computed Fields
- `avg_rating` — Mean rating across all user ratings for each movie
- `rating_count` — Number of user ratings per movie
- `user_ratings` — JSON array of individual {userId, rating} pairs for preference analysis

### Final Enriched Schema

| Column | Type | Source |
|--------|------|--------|
| movieId | integer | Original |
| title | text | Original |
| overview | text | Original |
| genres | text | Original |
| releaseDate | date | Original |
| runtime | integer | Original |
| budget | numeric | Original |
| revenue | numeric | Original |
| budget_tier | text | LLM-generated |
| revenue_tier | text | LLM-generated |
| avg_rating | numeric | Computed from ratings |
| rating_count | integer | Computed from ratings |
| user_ratings | jsonb | Aggregated from ratings |
| sentiment | text | LLM-generated |
| audience_appeal | text | LLM-generated |
| production_effectiveness_score | numeric | LLM-generated |

---

## Task 2: Movie System Design

### Tool Calling Architecture

Rather than having the LLM generate SQL directly, the system uses **Bedrock's tool calling (function calling)** capability. Claude is given a single tool — `query_table` — that queries the `enriched_movies` table with typed parameters:

```python
query_table(
    filters={"sentiment": "positive", "budget_tier": "blockbuster"},
    limit=10,
    order_by="production_effectiveness_score",
    ascending=False
)
```

**Why tool calling over raw SQL:**
- **Safety:** Claude never writes raw SQL — no injection risk
- **Control:** We define exactly what queries are possible through the schema
- **Reliability:** Typed parameters eliminate syntax errors
- **Auditability:** Every tool call is logged with inputs and outputs

### Agentic Conversation Loop

The system implements a multi-turn agentic loop where Claude autonomously decides what data to retrieve:

```
User Query → Claude → Tool Call? 
                        ├── Yes → Execute query → Return results → Claude → More data needed?
                        │                                                     ├── Yes → Another tool call
                        │                                                     └── No → Final answer
                        └── No → Final answer
```

For comparison queries, Claude typically makes 2+ tool calls (one per movie). For recommendations, it makes 1-2 calls with different filters. For user preferences, it fetches all movies and filters user ratings client-side.

### Supported Query Types

**1. Personalized Recommendations**
```
"Recommend action movies with positive sentiment"
"Show me blockbuster movies with low budget that performed really well"
"Top family movies with high production effectiveness"
```

**2. User Preference Summaries**
```
"Summarize preferences for userId 23"
"What kind of movies does userId 45 like?"
```

**3. Comparative Analysis**
```
"Compare Dog Day Afternoon vs Heat on production effectiveness"
"Which performed better financially: Dirty Harry or North by Northwest?"
```

---

## Prompt Engineering

### Iterative Prompt Development

The system prompt went through two iterations, with improvements driven by evaluation results.

### Version 1 — Initial Prompt

Basic task descriptions for each query type with minimal constraints. Issues discovered during evaluation:
- Genre hallucinations (recommending "Thriller" when user asked for "Action")
- Fabricating specific dollar amounts for budget/revenue (database only stores tiers)
- Confusing `avg_rating` (global average) with individual user ratings
- Calculating ROI ratios not present in the data

### Version 2 — Improved Prompt (Deployed)

Key improvements based on evaluation feedback:

**1. Strict Genre Rule:**
> "If the user asks for a specific genre (e.g., 'action'), only recommend movies whose genres field explicitly contains that genre word. Do NOT include adjacent genres (e.g., Thriller is not Action)."

**2. Anti-Hallucination Grounding Rules:**
> "NEVER invent or estimate specific dollar amounts for budget or revenue. The database only stores tiers — use those exact labels."
> "NEVER calculate ROI, return multiples, or revenue/budget ratios — this data is not available."

**3. Chain of Thought for User Preferences:**
Step-by-step instructions (Steps 1-5) that force Claude to:
- Fetch all movies first
- Parse `user_ratings` JSON for the specific userId
- Separate liked (≥4.0) vs disliked (≤2.0) movies
- Summarize patterns across genres, sentiment, budget tier
- Never confuse global `avg_rating` with individual user rating

**4. Data Grounding Constraint:**
> "Stick strictly to what the database returns — do not supplement with outside knowledge."

---

## Model Evaluation

### Evaluation Pipeline

A three-stage automated evaluation was implemented:

**Stage 1 — Data Snapshot:**
Fetch all 100 movies from Supabase to establish ground truth for evaluation.

**Stage 2 — Test Case Generation:**
Claude generates 10 test cases using only real data from the snapshot:
- 3 recommendation queries
- 3 user preference queries  
- 4 comparison queries

All test cases use verified titles, userIds, and filter values — preventing evaluation against hallucinated ground truth.

**Stage 3 — Model-Based Grading:**
A separate Claude instance grades each response on a 1-10 scale based on:
- Factual accuracy against the data snapshot
- Completeness (did it answer the full query?)
- Grounding (did it hallucinate any data?)
- Structure and clarity

### Results

| Metric | V1 (Initial Prompt) | V2 (Improved Prompt) |
|--------|--------------------|--------------------|
| **Average Score** | ~6.5/10 | **7.3/10** |
| Recommendation Quality | Genre mismatches, over-inclusion | Strict genre adherence |
| Preference Accuracy | Confused avg vs user rating | Correct separation |
| Comparison Quality | Invented ROI calculations | Data-grounded only |

**Score Breakdown by Query Type (V2):**

| Query Type | Avg Score | Notes |
|-----------|----------|-------|
| Recommendation | 7.0/10 | Strong genre matching, occasionally misses edge cases |
| User Preference | 6.0/10 | Improved with chain-of-thought, still complex |
| Comparison | 8.0/10 | Strongest category — accurate, well-structured |

### Sample High-Scoring Results

- **Score 9/10:** "Show me blockbuster movies with low budget that performed really well" — correctly identified all 3 matching movies with accurate data
- **Score 8/10:** "Compare Dog Day Afternoon vs Heat" — accurate metrics, proper budget efficiency analysis, well-reasoned conclusion
- **Score 8/10:** "Dirty Harry vs North by Northwest" — correctly identified identical metrics, appropriate tie conclusion

---

## Deployment

### Why Deploy?

The assignment asked for a system design. Deploying it demonstrates:
- The system works end-to-end, not just in a notebook
- Production-readiness considerations (health checks, scaling, secrets management)
- Full-stack engineering capability

### Deployment Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| Container Image | AWS ECR | Docker image storage |
| Orchestration | AWS EKS (Kubernetes) | 2-pod deployment with load balancing |
| LLM | AWS Bedrock | Claude Sonnet 4 inference |
| Database | Supabase | PostgreSQL with REST API |
| Frontend | AWS S3 | Static website hosting |

### Containerization

**Dockerfile:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "--workers", "2", "app:app"]
```

Key decisions:
- `python:3.11-slim` — minimal image (~150MB vs ~900MB for full)
- `--timeout 120` — LLM responses can take 30-60 seconds
- `--workers 2` — matches CPU allocation per pod
- Built with `--platform linux/amd64` — EKS runs x86, Mac uses ARM

### Kubernetes Configuration

**Deployment (2 replicas):**
- Resource requests: 250m CPU, 256Mi memory
- Resource limits: 500m CPU, 512Mi memory
- Liveness probe: `GET /health` every 30s
- Readiness probe: `GET /health` every 10s
- Supabase key stored as Kubernetes Secret

**Service (LoadBalancer):**
- Routes port 80 → port 8080 on pods
- AWS ELB distributes traffic across both pods

### Deployment Flow

```
1. docker build --platform linux/amd64    →  Local image
2. docker push to ECR                     →  Image in AWS registry
3. eksctl create cluster                  →  EKS cluster with 2 nodes
4. Attach IAM policies                    →  Bedrock + ECR access for nodes
5. kubectl create secret                  →  Supabase key
6. kubectl apply deployment + service     →  Pods running behind LoadBalancer
7. aws s3 cp index.html                   →  Frontend live on S3
```

---

## How to Run

### Prerequisites
- AWS CLI configured with appropriate permissions
- Docker Desktop running
- `eksctl` and `kubectl` installed
- Python 3.11+

### Option 1: Run Locally (Notebook)

```bash
pip install boto3 requests pandas pdfplumber
```

Open the Jupyter notebook and run cells in order. Requires AWS credentials configured and Bedrock model access enabled.

### Option 2: Deploy on EKS

```bash
# 1. Create ECR repo and push image
aws ecr create-repository --repository-name movie-assistant --region us-west-2
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-west-2.amazonaws.com
docker build --platform linux/amd64 -t movie-assistant .
docker tag movie-assistant:latest <ACCOUNT_ID>.dkr.ecr.us-west-2.amazonaws.com/movie-assistant:latest
docker push <ACCOUNT_ID>.dkr.ecr.us-west-2.amazonaws.com/movie-assistant:latest

# 2. Create EKS cluster (~15 min)
eksctl create cluster --name movie-assistant-cluster --region us-west-2 --nodegroup-name workers --node-type t3.medium --nodes 2 --managed

# 3. Configure IAM
aws iam attach-role-policy --role-name <NODE_ROLE> --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
aws iam attach-role-policy --role-name <NODE_ROLE> --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly

# 4. Deploy
kubectl create secret generic movie-assistant-secrets --from-literal=supabase-key=<YOUR_KEY>
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 5. Get endpoint
kubectl get svc movie-assistant-service

# 6. Host frontend
aws s3 mb s3://movie-assistant-web --region us-east-1
aws s3 website s3://movie-assistant-web --index-document index.html
aws s3 cp index.html s3://movie-assistant-web/
```

### Cleanup

```bash
eksctl delete cluster --name movie-assistant-cluster --region us-west-2
aws ecr delete-repository --repository-name movie-assistant --region us-west-2 --force
aws s3 rb s3://movie-assistant-web --force
```

---

## Repository Structure

```
Aetna_Assignment/
├── README.md                      # This file
├── db/                            # Original SQLite database
│   └── movies.db
├── notebooks/
│   ├── data_enrichment.ipynb      # Task 1: Data enrichment pipeline
│   └── movie_assistant.ipynb      # Task 2: System development & evaluation
├── app.py                         # Flask API (deployment-ready)
├── Dockerfile                     # Container build instructions
├── requirements.txt               # Python dependencies
├── index.html                     # Frontend UI
├── eval_dataset.json              # Generated evaluation test cases
├── eval_results.json              # Evaluation scores and analysis
└── k8s/
    ├── deployment.yaml            # Kubernetes deployment manifest
    └── service.yaml               # Kubernetes service manifest
```
