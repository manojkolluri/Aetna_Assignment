# Aetna Assignment — Movie Systems Design

## Demo

https://github.com/user-attachments/assets/acdb0141-daa7-40ca-be27-b72654e20138

**Live Website:** [http://movie-assistant-web.s3-website-us-east-1.amazonaws.com](http://movie-assistant-web.s3-website-us-east-1.amazonaws.com)

**Live API Endpoint:** `http://a623da9515ac547dfa84556caa73f711-1418076793.us-west-2.elb.amazonaws.com/ask`

---

## Task 1: Data Preparation & Enrichment

### Part 1 — Data Preprocessing

> Notebook: `Data_Prep.ipynb`

**The Problem:** Two SQLite databases were provided — `movies.db` (45,430 movies × 12 columns) and `ratings.db` (100,004 ratings × 5 columns). The task required working with a sample of 50–100 movies, so instead of backfilling missing values, I took an aggressive noise-elimination approach. With 45K records to work with, I could afford to drop anything imperfect and still end up with a clean, high-quality sample.

#### Movies Table Cleaning

**Null check:** The `language` column was entirely null (45,430 nulls across all rows). Dropped the entire column as it carried no information.

**Hidden data quality issues:** The initial `.isnull()` check passed for most columns, but a deeper inspection revealed problems that nulls don't catch — empty strings in `imdbId`, `overview`, and `releaseDate`; empty JSON arrays `[]` in `productionCompanies` and `genres`; and zero values in `budget` and `revenue` that represented missing data rather than actual zeros.

**Duplicate check:** `movieId` had 0 duplicates. `imdbId` had 16 duplicates — all were empty strings (movies without IMDb links), caught during empty string removal.

**Column-by-column cleaning:**

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
| `status` | 2 non-Released (Rumored, Post Production) | 2 | **5,184** |

**Why this approach:** Ideally, we would backfill missing budgets and revenues using external APIs or estimation models. But since the task only required 50–100 movies, eliminating noise was the faster and cleaner path — we had more than enough clean records to sample from.

#### Ratings Table Cleaning

**Basic stats:** 100,004 ratings from 671 unique users across 9,066 unique movies. Rating range: 0.5–5.0, average: 3.54. No nulls, no duplicates.

**Outlier removal:** Even though the data looked clean, I used normal distribution analysis to identify movies at the extreme ends of the rating spectrum — movies with unusually high or low numbers of ratings that could skew the sample. After removing outliers, the remaining ratings represented approximately **8,370 unique movies**.

#### Building the Final Sample

**Intersection:** Checked overlap between the cleaned movies (5,184) and the normal-band ratings (8,370). Found **841 movies** with both complete metadata and statistically normal rating distributions.

**Sampling:** Took a random sample of **100 movies** from these 841 (`random_state=42` for reproducibility).

**Rating aggregation:** For each movie, computed:
- `avg_rating` — mean rating across all users
- `rating_count` — total number of ratings
- `user_ratings` — JSON array of every individual `{userId, rating}` pair (used later for user preference analysis)

**Output:** Stored in `db/Final_movies.db` as the `Final_movies` table (100 rows × 14 columns).

---

### Part 2 — LLM Data Enrichment

> Notebook: `Data_Enrichment.ipynb`

*[PLACEHOLDER — share your enrichment notebook or describe what you did and I'll fill this in]*

---

## Task 2: Movie System Design

*[PLACEHOLDER]*

---

## Prompt Engineering

*[PLACEHOLDER]*

---

## Model Evaluation

*[PLACEHOLDER]*

---

## Deployment

*[PLACEHOLDER]*

---

## Repository Structure

```
Aetna_Assignment/
├── README.md
├── db/
│   ├── movies.db                  # Original movies database
│   ├── ratings.db                 # Original ratings database
│   └── Final_movies.db            # Preprocessed 100-movie sample
├── Data_Prep.ipynb                # Task 1 Part 1: Preprocessing
├── Data_Enrichment.ipynb          # Task 1 Part 2: LLM enrichment
├── Movie_Assistant.ipynb          # Task 2: System design & evaluation
├── app.py                         # Flask API (deployment)
├── Dockerfile
├── requirements.txt
├── index.html                     # Frontend UI
├── eval_dataset.json
├── eval_results.json
└── k8s/
    ├── deployment.yaml
    └── service.yaml
```
