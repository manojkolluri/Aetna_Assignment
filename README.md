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

> `Data_Prep.ipynb`

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

> `Data_Enrich.ipynb`

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

## Step 3: Movie System Design

> `Model_Build.ipynb`

*[PLACEHOLDER — share your Model_Build.ipynb and I'll document it]*

---

## Prompt Engineering

*[PLACEHOLDER]*

---

## Model Evaluation

*[PLACEHOLDER]*

---

## Deployment

*[PLACEHOLDER]*
