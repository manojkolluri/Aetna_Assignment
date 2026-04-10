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

*[PLACEHOLDER — share your Data_Enrich.ipynb and I'll document it]*

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
