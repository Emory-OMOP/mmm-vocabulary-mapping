# Graph-Augmented Vocabulary Tools and Semantic Concept Resolution for an MCP-Native OHDSI Agent

## Working Draft — Technical Methods and Design Rationale

**Last updated:** 2026-04-09

---

## 1. Introduction

The OHDSI standardized vocabularies contain 7.4M+ concepts across 60+ source vocabularies (SNOMED CT, RxNorm, LOINC, ICD-10-CM, etc.), connected by 46M+ relationship edges. Navigating this space programmatically — finding paths between concepts, resolving free text to standard concepts, and curating concept sets — requires capabilities beyond simple keyword search.

We describe the design and implementation of graph traversal tools and a hybrid semantic search pipeline integrated into an MCP-native OHDSI vocabulary server. The system extends a prior vocabulary lookup server [1] with three categories of new capability: (a) knowledge graph pathfinding and exploration, (b) ontology-aware semantic concept resolution, and (c) phenotype-aware concept set curation.

## 2. Prior Work

### 2.1 omop-graph (Australian Cancer Data Network)

Kennedy (UNSW) developed omop-graph, a Python knowledge graph library for OMOP vocabulary traversal [2]. The library provides bidirectional BFS pathfinding, path scoring with transparent quality metrics, subgraph exploration, term grounding with hierarchy constraints, phenotype simplification via common parent identification, and an OAK-compliant ontology interface. The implementation targets PostgreSQL via SQLAlchemy with the omop-alchemy ORM.

We evaluated omop-graph for integration into our DuckDB-backed MCP server. The core algorithms (bidirectional BFS, path profiling, subgraph traversal) were ported with significant architectural adaptation: raw DuckDB SQL replaced SQLAlchemy, batch edge fetching replaced per-node queries with LRU caching, and runtime predicate classification from the RELATIONSHIP table replaced custom extension tables (§3.1). The oaklib interface, omop-alchemy ORM, and CLI loader were not adopted (§4.1).

### 2.2 omop-emb (Australian Cancer Data Network)

The companion omop-emb library [3] provides a backend-agnostic embedding layer for OMOP concepts with pgvector and FAISS storage backends. Key design patterns include a query embedding reuse strategy (reusing stored concept embeddings as proxies for free-text queries when exact matches exist), a resolver cascade with confidence tiers (exact → synonym → partial → fulltext → embedding), and domain/vocabulary filtering at search time rather than post-filtering.

We adopted the resolver cascade pattern and query embedding reuse strategy but replaced the storage backend (§3.3). The pgvector and FAISS backends both require PostgreSQL for concept metadata; our implementation uses DuckDB's native VSS extension with HNSW indexing, which is portable to pgvector when the infrastructure migrates to PostgreSQL.

### 2.3 Biomedical Entity Linking Literature

Several recent advances informed our semantic search design:

**SapBERT** (Liu et al., 2021) [4] introduced self-alignment pretraining for biomedical entity representation, training on UMLS concept pairs to learn that synonymous terms (e.g., "MI", "Myocardial infarction", "Heart attack") should occupy nearby positions in embedding space. SapBERT achieves state-of-the-art performance on six medical entity linking benchmarks without task-specific fine-tuning.

**CODER** (Yuan et al., 2022) [5] extends this approach cross-lingually via contrastive learning on the UMLS knowledge graph, outperforming SapBERT on zero-shot term normalization and relation classification.

**Hybrid re-ranking** (Gnecco & Serrano, BioNNE-L 2025) [6] demonstrated that combining SapBERT embedding cosine similarity with lexical measures (Jaccard token overlap, Levenshtein string distance) via optimized weighting corrects errors where either approach alone fails. The system achieved first place in Accuracy\@1 (0.70) at the BioNNE-L 2025 biomedical entity linking competition.

**KEEP** (Elhussein et al., PMLR 2025) [7] showed that embedding text enriched with knowledge graph context (parent concepts, hierarchical position) outperforms text-only embeddings for clinical code prediction. Their approach first generates embeddings from knowledge graphs, then refines with clinical data while regularizing to preserve ontological structure.

**LLM-mediated normalization** (HeaLing Workshop, ACL 2026) [8] demonstrated that preprocessing lay or informal text through an LLM to generate preferred clinical terms before embedding-based lookup improves normalization accuracy from 0.574 (MetaMap) to 0.858, particularly for social media and patient-authored text.

## 3. Methods

### 3.1 Knowledge Graph Tools

Three MCP tools were implemented by porting algorithms from omop-graph [2] and adapting them for a DuckDB backend with batch-oriented query patterns.

#### 3.1.1 Bidirectional BFS Pathfinding (`find_concept_paths`)

Given source and target concept IDs, the algorithm discovers shortest paths through the CONCEPT_RELATIONSHIP graph using bidirectional breadth-first search. Unlike the precomputed CONCEPT_ANCESTOR table (which provides transitive closure for hierarchical relationships only), this traversal follows all relationship types — ontological ("Is a"), mapping ("Maps to"), compositional ("Has ingredient"), versioning ("Replaced by") — enabling discovery of cross-vocabulary connection chains.

**Adaptation from omop-graph:** The original implementation expands one node per iteration, issuing individual `iter_edges()` calls backed by SQLAlchemy LRU caches. Our implementation collects the full BFS frontier at each depth level and issues a single batched query (`WHERE concept_id_1 IN (...)`) per expansion. This exploits DuckDB's vectorized execution model, where scanning a column segment and matching against an IN list is faster than N individual point lookups, even with caching. A per-node edge cap of 200 prevents frontier explosion on hub concepts (e.g., "Clinical Finding" with 100K+ descendants).

**Why not recursive CTEs:** We evaluated pushing the BFS into a PostgreSQL recursive CTE for single-round-trip execution. Recursive CTEs lack bidirectional search (exponential search space reduction), early termination when the shortest path is found, per-node edge caps, and dynamic predicate filtering per expansion. For the general pathfinding case with dense hub nodes, the Python BFS with batch fetching outperforms the CTE approach.

**Path scoring** uses a `PathProfile` ranking tuple that penalizes (in priority order): invalid concepts, non-standard concepts, metadata edges, mapping edges, vocabulary switches, and hop count. This is adapted from omop-graph's scoring module, simplified to remove embedding-based relevance scoring in favor of the hybrid re-ranking approach applied at the concept resolution layer (§3.3).

#### 3.1.2 Subgraph Exploration (`explore_concept_graph`)

BFS from seed concepts with configurable depth (1–4) and node limit (1–200), returning the full neighborhood graph (nodes + edges with metadata). Unlike `get_concept_relationships` (single-hop, flat table) or `get_concept_ancestors` (precomputed hierarchy only), this tool follows all relationship types across multiple hops.

#### 3.1.3 Predicate Classification

OMOP's RELATIONSHIP table contains 722 relationship types with no semantic categorization. omop-graph introduced a classification scheme stored in custom extension tables (RelationshipClass, RelationshipMapping) via the omop-alchemy ORM. We replicate this classification at runtime using standard RELATIONSHIP table fields:

| Category | Classification Rule | Examples |
|----------|-------------------|----------|
| ONTOLOGICAL | `defines_ancestry = 1` | Is a, Subsumes, Ingredient of |
| MAPPING | name contains "maps to", "mapped from", "equivalent" | Maps to, Mapped from |
| VERSIONING | name contains "replaced", "replaces" | Concept replaced by |
| ATTRIBUTE | name starts with "has " or reverse does | Has dose form, Has ingredient |
| METADATA | default | All others |

This eliminates the dependency on extension tables while preserving the ability to filter traversal by semantic edge type.

### 3.2 Concept Embeddings for Semantic Search

#### 3.2.1 Embedding Model Selection

We evaluated three embedding models across a spectrum from general-purpose to biomedical-specific (Section 5). Based on the results of a 3-model × 2-condition experiment:

**Selected model:** cambridgeltl/SapBERT-from-PubMedBERT-fulltext [4] (768 dimensions) with **name-only** concept text.

SapBERT achieved the highest overall accuracy (Acc@1=0.433, MRR=0.491) across formal clinical terms, lay language, and abbreviations. Its self-alignment pretraining on 4M+ UMLS concept pairs is specifically designed for matching surface forms to canonical medical concepts, and this advantage was most pronounced on abbreviations (Acc@1=0.400) where UMLS synonym knowledge is critical.

#### 3.2.2 Embedding Text: Name-Only vs. Enriched

A key finding of our evaluation (Section 5.6) is that **enriching concept embedding text with synonyms, parent concepts, domain, and vocabulary degrades retrieval accuracy** by 2-5x across all models tested. We initially hypothesized, following the KEEP framework [7], that augmenting embedding text with ontological context would improve quality. The enriched format was:

```
{concept_name} | {synonym_1} | ... | {synonym_5} | {parent_1} | {parent_2} | {parent_3} | {domain_id} | {vocabulary_id}
```

In practice, this diluted the embedding signal: the model averages across all tokens, so appending synonyms and parent names pushes the embedding toward a vague centroid rather than the concept's core meaning. Furthermore, the query-concept asymmetry (short query text vs. long enriched concept text) places them in different regions of the embedding space.

The production configuration embeds concept names only, matching the format these models were trained and benchmarked on.

#### 3.2.3 Embedding Generation and Storage

Embeddings for 3,240,761 standard OMOP concepts are generated in three phases:

1. **Embed** (Phase 1): Concepts encoded on Apple MPS with length-sorted batching (short texts first) to minimize padding waste. Batch size progressively reduced for the longest texts (256 → 64 → 8) to avoid GPU memory exhaustion. Embeddings saved as raw `.npy` file for crash recovery before proceeding.
2. **Store** (Phase 2): Embeddings written to DuckDB via batched `executemany` inserts with `FLOAT[768]` array column. Memory-mapped `.npy` read avoids holding the full 9.4 GB embedding array in Python memory during the write phase.
3. **Index** (Phase 3): HNSW index built with `ef_construction=128, M=16` for approximate nearest neighbor search with cosine metric.

The resulting DuckDB file (~25 GB for name-only, 768-dim) is portable — embeddings can be exported to pgvector via parquet with zero recomputation when the infrastructure migrates to PostgreSQL.

### 3.3 Hybrid Concept Resolution

#### 3.3.1 Resolver Cascade

Concept resolution follows a tiered strategy inspired by omop-emb's resolver pipeline [3]:

1. **Exact match** — ILIKE on concept_name (highest confidence)
2. **Synonym match** — ILIKE on concept_synonym (planned, not yet wired)
3. **Embedding search** — SapBERT cosine similarity via HNSW index (planned, not yet wired)
4. **LLM normalization** — Agent normalizes lay terms to clinical terminology before search (via tool docstring guidance, per HeaLing 2026 [8])

Early stopping: if tier 1 returns high-confidence results (exact name match), lower tiers are skipped.

#### 3.3.2 Hybrid Re-Ranking

Following Gnecco & Serrano (2025) [6], candidates from any resolver tier are re-ranked using a weighted combination of:

- **Levenshtein similarity** (0.4 weight) — catches typos and minor surface variations
- **Jaccard token overlap** (0.4 weight) — catches reworded phrases with shared clinical tokens
- **Brevity bonus** (0.2 weight) — favors shorter, more specific concept names over verbose descriptions

This hybrid score replaces the original ILIKE-based ordering (exact prefix match first, then name length). When hierarchy constraints are active (parent_concept_id), candidates are first filtered by CONCEPT_ANCESTOR reachability, then sorted by separation distance with hybrid score as tiebreaker.

### 3.4 Phenotype Simplification (Planned)

The `find_common_parents` algorithm from omop-graph [2] identifies the minimum set of parent concepts that subsumes a given set of seed concepts, computing coverage (seeds captured), pollution (irrelevant descendants included), completeness (fraction of seeds covered), and purity (coverage / total descendants) metrics. A greedy set-cover algorithm then selects the optimal parent set balancing coverage against pollution.

This will be exposed as a `find_common_ancestor` MCP tool for automated concept set curation — the algorithmic equivalent of the manual process phenotype authors perform in ATLAS when selecting parent concepts for descendant-inclusive concept sets.

## 4. Design Decisions

### 4.1 What Was Not Adopted from omop-graph

| Component | Reason for exclusion |
|-----------|---------------------|
| omop-alchemy ORM | Raw SQL preferred for query transparency during BFS debugging; avoids coupling to external fork's release cadence; our SQL is already ANSI-portable across DuckDB and PostgreSQL |
| oaklib interface | Ecosystem interoperability feature, not agent-facing; deferred until needed for external tool compatibility |
| PostgreSQL tsvector search | DuckDB lacks tsvector; replaced by embedding-based semantic search which is strictly more capable |
| Extension tables (RelationshipClass/RelationshipMapping) | Runtime classification from standard RELATIONSHIP fields achieves equivalent result without schema modifications |
| CLI vocabulary loader | Our ETL uses dbt; incompatible pipeline |

### 4.2 Database Architecture

The system operates on DuckDB for all vocabulary queries and embedding search. All SQL is written to be ANSI-compatible, so the backend could be swapped to PostgreSQL (e.g., for native pgvector embedding storage or OHDSI ecosystem alignment with ATLAS/WebAPI/Achilles) as a connection-layer change rather than a query rewrite.

### 4.3 Embedding Model and Text Format Selection

Initial development used bge-small-en-v1.5 (384 dims, general-purpose) with enriched text (concept name + synonyms + parents + domain + vocabulary). Informal testing suggested domain-specific models might improve results, leading to a systematic evaluation of three models under two text conditions (Section 5).

The experiment revealed two counter-intuitive findings: (1) text enrichment with synonyms and ancestry context was uniformly harmful across all models, and (2) SapBERT — which performed worst on enriched text due to its design for short entity mentions — performed best on name-only text, which is the format matching its training data. The final selection (SapBERT name-only) was driven by data, not by the initial hypothesis.

## 5. Experiment: Embedding Model Comparison for OMOP Concept Resolution

### 5.1 Motivation

The choice of embedding model for semantic concept search involves a trade-off between general-purpose text understanding and biomedical domain specificity. Prior work offers conflicting guidance: SapBERT [4] achieved state-of-the-art on medical entity linking benchmarks, while a 2025 study benchmarking 36 transformer models for biomedical terminology standardization found that general-purpose models (all-MiniLM-L12-v2, e5-large, all-mpnet-base-v2) outperformed biomedical-specific models (SapBERT, ClinicalBERT, BioGPT) on concept matching tasks [9]. BioLORD-2023 [10] occupies a middle ground, combining ontological knowledge (SNOMED CT, UMLS) with general semantic similarity training, and established new state-of-the-art on both biomedical concept representation and clinical sentence similarity.

Existing benchmarks for medical concept normalization — MCN [12], ShARe/CLEF 2013 [13], n2c2 2019 — evaluate entity linking from clinical narrative text to UMLS CUIs. The Consumer Health Vocabulary (CHV) [14] provides 158K lay-to-professional term mappings integrated into UMLS, but has not been updated since 2011 and does not target OMOP concept_ids. No existing evaluation set addresses the specific task of mapping diverse user queries (formal clinical terms, lay patient language, and clinical abbreviations) to standard concepts within the full 3.24M-concept OMOP vocabulary space, which uniquely spans 60+ source vocabularies (SNOMED CT, RxNorm, LOINC, ICD-10-CM, CPT4, etc.) simultaneously.

We construct a tiered evaluation set and use it to compare three embedding models spanning the general-purpose to biomedical-specific spectrum, determining which best serves OMOP vocabulary search in an agentic context.

### 5.2 Models Under Evaluation

| Model | Dimensions | Training Data | Architecture | Category |
|-------|-----------|---------------|-------------|----------|
| sentence-transformers/all-mpnet-base-v2 [11] | 768 | 1B+ sentence pairs (contrastive) | MPNet-base | General-purpose (biomedical benchmark winner [9]) |
| cambridgeltl/SapBERT-from-PubMedBERT-fulltext [4] | 768 | UMLS 2020AA concept pairs (self-alignment) | PubMedBERT | Biomedical entity linking |
| FremyCompany/BioLORD-2023 [10] | 768 | SNOMED CT + UMLS + AGCT definitions (contrastive + self-distillation) | all-mpnet-base-v2 | Biomedical ontology-aware |

All models produce 768-dimensional normalized embeddings, enabling direct comparison with identical DuckDB schema, HNSW index configuration, and storage footprint across conditions. All are compatible with the sentence-transformers library.

The pairing of all-mpnet-base-v2 with BioLORD-2023 is intentional: BioLORD-2023 is fine-tuned from all-mpnet-base-v2, so comparing the two isolates the contribution of ontological fine-tuning from the base model's general semantic capabilities.

### 5.3 Embedding Generation Protocol

Each model embeds the same 3,240,761 standard OMOP concepts (standard_concept = 'S', invalid_reason IS NULL) from Athena vocabulary v5.0 under two text conditions:

**Name-only:** Embedding text = `{concept_name}` (the raw OMOP concept name, no additional context).

**Enriched:** Embedding text = `{concept_name} | {synonym_1} | ... | {synonym_5} | {parent_1} | {parent_2} | {parent_3} | {domain_id} | {vocabulary_id}`, where synonyms (up to 5) come from CONCEPT_SYNONYM, parents (up to 3) from CONCEPT_ANCESTOR at min_levels_of_separation=1, and text is truncated at 1,500 characters.

Texts are sorted by length before batching to minimize padding waste. Batch size is progressively reduced for the longest texts (256 → 64 → 8) to avoid GPU memory exhaustion on Apple MPS.

Embeddings are stored in DuckDB with HNSW indexing (ef_construction=128, M=16, cosine metric) via the DuckDB VSS extension. This yields 6 total embedding databases (3 models × 2 text conditions).

### 5.4 Evaluation Protocol

#### 5.4.1 Test Set Construction

No existing benchmark maps lay terminology to OMOP concept_ids. Prior concept normalization datasets target UMLS CUIs from clinical narrative (MCN [12], ShARe/CLEF [13], n2c2 2019) or patient forums (CHV [14]). These address entity linking in context — identifying and normalizing a mention span within a sentence — rather than vocabulary search, where the input is an isolated query term and the target is the best-matching concept in a 3.24M-entry catalog.

We construct a pilot evaluation set of 30 query terms organized into three tiers of increasing difficulty. This pilot set is designed to validate the experimental framework; a larger evaluation set can be derived from CHV's 158K lay-to-professional mappings filtered to concepts present in the OMOP vocabulary, providing hundreds of validated lay-term pairs for a more statistically powered analysis.

**Tier 1 — Formal clinical terms** (baseline; all models should perform well):
Terms that closely match standard OMOP concept names.

| Query | Expected concept_id | Expected concept_name | Domain |
|-------|-------------------|-----------------------|--------|
| myocardial infarction | 4329847 | Myocardial infarction | Condition |
| type 2 diabetes mellitus | 201826 | Type 2 diabetes mellitus | Condition |
| essential hypertension | 320128 | Essential hypertension | Condition |
| metformin | 1503297 | metformin | Drug |
| serum creatinine | 3016723 | Creatinine [Mass/volume] in Serum or Plasma | Measurement |
| acetaminophen | 1125315 | acetaminophen | Drug |
| atrial fibrillation | 313217 | Atrial fibrillation | Condition |
| colonoscopy | 4249893 | Colonoscopy | Procedure |
| hemoglobin A1c | 3004410 | Hemoglobin A1c/Hemoglobin.total in Blood | Measurement |
| major depressive disorder | 440383 | Depressive disorder | Condition |

**Tier 2 — Lay/informal terms** (the key differentiator):
Common patient language that requires semantic bridging to clinical terminology.

| Query | Expected concept_id | Expected concept_name | Domain |
|-------|-------------------|-----------------------|--------|
| heart attack | 4329847 | Myocardial infarction | Condition |
| sugar diabetes | 201826 | Type 2 diabetes mellitus | Condition |
| high blood pressure | 320128 | Essential hypertension | Condition |
| broken leg | 4185758 | Fracture of lower leg | Condition |
| water pill | 974166 | hydrochlorothiazide | Drug |
| blood thinner | 1310149 | warfarin | Drug |
| lung cancer | 4115276 | Non-small cell lung cancer | Condition |
| kidney function test | 3016723 | Creatinine [Mass/volume] in Serum or Plasma | Measurement |
| the shaking disease | 381270 | Parkinson's disease | Condition |
| tummy ache | 200219 | Abdominal pain | Condition |

**Tier 3 — Ambiguous/challenging terms** (stress test):
Terms requiring disambiguation, abbreviation expansion, or cross-vocabulary reasoning.

| Query | Expected concept_id | Expected concept_name | Domain |
|-------|-------------------|-----------------------|--------|
| MI | 4329847 | Myocardial infarction | Condition |
| COPD | 255573 | Chronic obstructive lung disease | Condition |
| T2DM | 201826 | Type 2 diabetes mellitus | Condition |
| BP meds | 904542 | Antihypertensive therapy | Drug |
| chemo | 4273629 | Chemotherapy | Procedure |
| dialysis | 4146536 | Dialysis | Procedure |
| A1c | 3004410 | Hemoglobin A1c/Hemoglobin.total in Blood | Measurement |
| echo | 4205572 | Echocardiography | Procedure |
| sed rate | 3013707 | Erythrocyte sedimentation rate | Measurement |
| scope | 4249893 | Colonoscopy | Procedure |

#### 5.4.2 Retrieval Metrics

For each query, the top-k (k=1, 5, 10) results are retrieved via cosine similarity against the embedding index, filtered by the expected domain. We report:

- **Accuracy@1 (Acc@1):** Fraction of queries where the expected concept appears as the top result
- **Accuracy@5 (Acc@5):** Fraction of queries where the expected concept appears in the top 5
- **Accuracy@10 (Acc@10):** Fraction of queries where the expected concept appears in the top 10
- **Mean Reciprocal Rank (MRR):** Average of 1/rank for the expected concept (0 if not in top-k)
- **Mean Similarity:** Average cosine similarity of the expected concept when found

Metrics are reported per tier and overall to characterize performance on formal, lay, and ambiguous queries separately.

#### 5.4.3 Experimental Conditions

Each model is evaluated under two text encoding conditions:

1. **Name-only:** Embedding text = `{concept_name}` (raw concept name only)
2. **Enriched:** Embedding text = concept name + up to 5 synonyms + up to 3 parent concepts + domain + vocabulary

This 3-model × 2-condition design (6 total embedding runs) isolates the contribution of text enrichment from model choice.

#### 5.4.4 Hybrid Re-Ranking Evaluation

Following Gnecco & Serrano [6], each retrieval condition is additionally evaluated with hybrid re-ranking applied to the top-50 cosine results:

- **Cosine only:** Raw embedding similarity ranking
- **Hybrid:** Weighted blend of cosine similarity (0.4), Levenshtein ratio (0.3), and Jaccard token overlap (0.3)

This 6-condition × 2-ranking design (12 total evaluations) determines whether hybrid re-ranking compensates for weaker embedding models.

#### 5.4.5 Computational Cost

For each model, we report:
- Embedding generation time (3.24M concepts on Apple M-series MPS)
- DuckDB file size (storage footprint)
- Query latency (median time per semantic search query)

### 5.5 Infrastructure

- **Hardware:** Apple Mac Studio (M-series, MPS acceleration)
- **Vocabulary:** OHDSI Athena v5.0, 3,240,761 standard concepts
- **Vector Index:** DuckDB VSS extension, HNSW (ef_construction=128, M=16, cosine)
- **Embedding Framework:** sentence-transformers (Python)
- **Query Protocol:** Encode query text with same model, cosine similarity search via DuckDB `array_cosine_similarity()`, domain-filtered

### 5.6 Results

#### 5.6.1 Overall Performance

| Condition | Acc@1 | Acc@5 | Acc@10 | MRR | Mean Sim |
|-----------|-------|-------|--------|-----|----------|
| **SapBERT name-only** | **0.433** | **0.567** | 0.633 | **0.491** | 0.885 |
| BioLORD name-only | 0.333 | **0.567** | **0.667** | 0.454 | 0.863 |
| mpnet name-only | 0.333 | 0.500 | 0.533 | 0.405 | 0.867 |
| SapBERT enriched | 0.167 | 0.267 | 0.333 | 0.215 | 0.630 |
| BioLORD enriched | 0.067 | 0.133 | 0.267 | 0.110 | 0.654 |
| mpnet enriched | 0.067 | 0.100 | 0.133 | 0.080 | 0.695 |

#### 5.6.2 Performance by Tier

**Tier 1 — Formal clinical terms (n=10):**

| Condition | Acc@1 | Acc@5 | Acc@10 | MRR |
|-----------|-------|-------|--------|-----|
| mpnet name-only | 0.700 | 0.900 | 0.900 | 0.800 |
| BioLORD name-only | **0.700** | **0.900** | **1.000** | 0.784 |
| SapBERT name-only | 0.700 | 0.800 | 0.900 | 0.762 |
| SapBERT enriched | 0.300 | 0.600 | 0.600 | 0.420 |
| BioLORD enriched | 0.200 | 0.400 | 0.600 | 0.302 |
| mpnet enriched | 0.200 | 0.300 | 0.300 | 0.225 |

**Tier 2 — Lay/informal terms (n=10):**

| Condition | Acc@1 | Acc@5 | Acc@10 | MRR |
|-----------|-------|-------|--------|-----|
| **SapBERT name-only** | **0.200** | **0.400** | **0.500** | **0.262** |
| mpnet name-only | 0.100 | 0.300 | 0.300 | 0.150 |
| BioLORD name-only | 0.000 | 0.400 | 0.500 | 0.211 |
| SapBERT enriched | 0.100 | 0.100 | 0.200 | 0.110 |
| BioLORD enriched | 0.000 | 0.000 | 0.100 | 0.013 |
| mpnet enriched | 0.000 | 0.000 | 0.000 | 0.000 |

**Tier 3 — Abbreviations/ambiguous (n=10):**

| Condition | Acc@1 | Acc@5 | Acc@10 | MRR |
|-----------|-------|-------|--------|-----|
| **SapBERT name-only** | **0.400** | **0.500** | **0.500** | **0.450** |
| BioLORD name-only | 0.300 | 0.400 | 0.500 | 0.367 |
| mpnet name-only | 0.200 | 0.300 | 0.400 | 0.264 |
| SapBERT enriched | 0.100 | 0.100 | 0.200 | 0.114 |
| BioLORD enriched | 0.000 | 0.000 | 0.100 | 0.014 |
| mpnet enriched | 0.000 | 0.000 | 0.100 | 0.014 |

#### 5.6.3 Notable Misses (SapBERT name-only)

Despite being the best-performing condition, SapBERT name-only failed to place the expected concept in the top 10 for 11 of 30 queries:

| Tier | Query | Expected | Top Result (similarity) |
|------|-------|----------|------------------------|
| formal | serum creatinine | Creatinine [Mass/volume] in Serum or Plasma | Creatinine measurement, serum (0.960) |
| lay | water pill | hydrochlorothiazide | Water Oral Tablet (0.762) |
| lay | blood thinner | warfarin | tranexamic acid Injection (0.518) |
| lay | kidney function test | Creatinine [Mass/volume] in Serum or Plasma | Renal function tests (0.909) |
| lay | the shaking disease | Parkinson's disease | Fear of shaking (0.685) |
| lay | tummy ache | Abdominal pain | Aching pain (0.816) |
| abbr | BP meds | Antihypertensive therapy | BOMEDEMSTAT (0.598) |
| abbr | A1c | Hemoglobin A1c/Hemoglobin.total in Blood | Hemoglobin A1c measurement (0.887) |
| abbr | echo | Echocardiography | Echocardiography (0.801) |
| abbr | sed rate | Erythrocyte sedimentation rate | Erythrocyte sedimentation rate (0.696) |
| abbr | scope | Colonoscopy | Endoscopy (0.673) |

Several misses are near-hits where the expected concept is a specific OMOP formulation (e.g., LOINC's "Creatinine [Mass/volume] in Serum or Plasma") but the model returns a semantically correct broader concept (e.g., SNOMED's "Creatinine measurement, serum"). Others reflect lay-to-clinical gaps that no embedding model can bridge without synonym table lookup or LLM normalization ("water pill" → hydrochlorothiazide, "the shaking disease" → Parkinson's).

### 5.7 Discussion

#### 5.7.1 Text Enrichment is Harmful

The most significant finding is that enriching concept embedding text with synonyms, parent concepts, and vocabulary metadata **uniformly degraded performance** across all three models and all three query tiers. Enriched conditions scored 2-5x worse than name-only on every metric.

This contradicts the KEEP framework's finding [7] that ontological context improves embeddings. However, the mechanisms differ: KEEP uses knowledge graph structure during model training (as a regularization target), while our approach concatenated ontological text into the embedding input at inference time. The distinction is between learning ontological relationships implicitly (KEEP) vs. injecting them as surface text (our approach). The latter produces longer, more heterogeneous input strings that dilute the embedding signal, particularly for models like SapBERT that were trained on short entity mentions.

Additionally, the query-concept asymmetry — short query strings ("heart attack") compared against long enriched concept strings ("Myocardial infarction | Heart attack | Acute coronary event | Ischemic heart disease | Condition | SNOMED") — places queries and concepts in different regions of the embedding space, reducing cosine similarity even for correct matches.

#### 5.7.2 Model Selection: SapBERT vs. BioLORD-2023

SapBERT outperformed BioLORD-2023 on Acc@1 (0.433 vs 0.333) and MRR (0.491 vs 0.454), while BioLORD matched or slightly exceeded on Acc@5 and Acc@10. The difference is concentrated in Tier 2 (lay terms) and Tier 3 (abbreviations), where SapBERT's UMLS self-alignment training provides a direct advantage: it has seen "COPD", "MI", "A1c", and "chemo" as synonyms for their respective UMLS concepts during pretraining.

BioLORD-2023 was trained on SNOMED concept definitions rather than synonym pairs, giving it stronger sentence-level semantics [10] but less direct synonym-to-concept mapping. For the specific task of vocabulary search (matching short query terms to concept names), SapBERT's synonym-pair training is a better fit than BioLORD's definition-based training.

all-mpnet-base-v2 (the base model for BioLORD) performed worst, confirming that biomedical fine-tuning (whether SapBERT's self-alignment or BioLORD's ontological training) adds measurable value over general-purpose embeddings for clinical concept resolution.

#### 5.7.3 Limitations of Embedding-Only Search

Even the best condition (SapBERT name-only) achieved only 0.433 Acc@1, with 11/30 queries failing to place the expected concept in the top 10. The failures cluster into three categories:

1. **Lay-to-clinical semantic gaps** — "water pill" → hydrochlorothiazide, "blood thinner" → warfarin, "the shaking disease" → Parkinson's disease. No embedding model bridges these because they are cultural/colloquial associations, not semantic similarity. These require either CONCEPT_SYNONYM table lookup (which contains "Heart attack" → "Myocardial infarction") or LLM-mediated normalization [8].

2. **OMOP-specific name formats** — LOINC names like "Creatinine [Mass/volume] in Serum or Plasma" are highly structured strings that don't match natural-language queries like "serum creatinine". The SNOMED equivalent ("Creatinine measurement, serum") is found but has a different concept_id. Cross-vocabulary concept resolution is needed.

3. **Ambiguous abbreviations** — "scope" → Colonoscopy is too large a semantic leap; "echo" → Echocardiography returns the correct concept name but a different concept_id in the OMOP hierarchy.

These findings validate the resolver cascade architecture (Section 3.3): exact name match and synonym search handle the cases where embeddings fail, while embeddings handle the cases where string matching fails. The two approaches are complementary, not substitutes.

#### 5.7.4 Implications for Production

Based on these results, the production concept resolution pipeline uses:

1. **ILIKE name match** (Tier 1 queries — formal terms matching concept names directly)
2. **CONCEPT_SYNONYM search** (Tier 2 queries — lay terms that are curated synonyms, e.g., "heart attack")
3. **SapBERT name-only embedding search** (fallback for queries not matched by steps 1-2)
4. **LLM normalization** (agent normalizes lay terms to clinical vocabulary before searching, e.g., "water pill" → "diuretic")
5. **Hybrid re-ranking** [6] on the combined candidate set (Levenshtein + Jaccard + brevity scoring)

## 6. References

[1] Smith D, Marquez J, Rhodes J, Zhang X, Budiman B. An MCP-Native Architecture for Agentic OMOP Vocabulary and Clinical Data Access. Accepted, OHDSI Europe 2026.

[2] Kennedy G. omop-graph: Explainable, OMOP-native knowledge graph traversal and pathfinding. Australian Cancer Data Network / UNSW. https://github.com/AustralianCancerDataNetwork/OMOP_Graph (spires branch).

[3] Kennedy G. omop-emb: Backend-agnostic embedding layer for OMOP concepts. Australian Cancer Data Network. https://github.com/AustralianCancerDataNetwork/omop-emb (faiss branch).

[4] Liu F, Shareghi E, Meng Z, Basaldella M, Collier N. Self-Alignment Pretraining for Biomedical Entity Representations. Proceedings of NAACL-HLT 2021. https://huggingface.co/cambridgeltl/SapBERT-from-PubMedBERT-fulltext

[5] Yuan Z, Zhao Z, Sun H, Li J, Wang F, Yu S. CODER: Knowledge-infused cross-lingual medical term embedding for term normalization. Journal of Biomedical Informatics. 2022;126:103983. https://doi.org/10.1016/j.jbi.2021.103983

[6] Gnecco G, Serrano JC. Hybrid Re-ranking for Biomedical Entity Linking using SapBERT Embeddings: A High-Performance System for BioNNE-L 2025-1. CEUR Workshop Proceedings, Vol. 4038. https://ceur-ws.org/Vol-4038/paper_35.pdf

[7] Elhussein M, et al. KEEP: Integrating Medical Ontologies with Clinical Data for Robust Code Embeddings. Proceedings of the Conference on Health, Inference, and Learning (CHIL), PMLR 2025. https://arxiv.org/abs/2510.05049

[8] Normalizing Health Concepts with Biomedical Embedding and LLMs. Proceedings of the HeaLing Workshop, ACL 2026. https://aclanthology.org/2026.healing-1.15/

[9] Keller M, et al. Benchmarking Transformer Embedding Models for Biomedical Terminology Standardization. Journal of Biomedical Informatics. 2025. https://doi.org/10.1016/j.jbi.2025.104776

[10] Remy F, Demuynck K, Demeester T. BioLORD-2023: Semantic Textual Representations Fusing Large Language Models and Clinical Knowledge Graph Insights. Journal of the American Medical Informatics Association. 2024;31(9):1844-1855. https://doi.org/10.1093/jamia/ocae120

[11] Song K, Tan X, Qin T, Lu J, Liu TY. MPNet: Masked and Permuted Pre-training for Language Understanding. NeurIPS 2020. Model: https://huggingface.co/sentence-transformers/all-mpnet-base-v2

[12] Luo Y, et al. MCN: A Comprehensive Corpus for Medical Concept Normalization. Journal of Biomedical Informatics. 2019;92:103132. https://doi.org/10.1016/j.jbi.2019.103132

[13] Suominen H, et al. Overview of the ShARe/CLEF eHealth Evaluation Lab 2013. Information Access Evaluation. Multilinguality, Multimodality, and Visualization. CLEF 2013. https://doi.org/10.1186/s13326-016-0084-y

[14] Doing-Harris K, Zeng-Treitler Q. Computer-Assisted Update of a Consumer Health Vocabulary Through Mining of Social Network Data. Journal of Medical Internet Research. 2011;13(2):e37. Ontology: Cardillo E, et al. Ontology of Consumer Health Vocabulary: Providing a Formal and Interoperable Semantic Resource for Linking Lay Language and Medical Terminology. Applied Sciences. 2023;13(24):13224. CHV Files: https://biomedinfo.smhs.gwu.edu/chv-files

[1] Smith D, Marquez J, Rhodes J, Zhang X, Budiman B. An MCP-Native Architecture for Agentic OMOP Vocabulary and Clinical Data Access. Accepted, OHDSI Europe 2026.

[2] Kennedy G. omop-graph: Explainable, OMOP-native knowledge graph traversal and pathfinding. Australian Cancer Data Network / UNSW. https://github.com/AustralianCancerDataNetwork/OMOP_Graph (spires branch).

[3] Kennedy G. omop-emb: Backend-agnostic embedding layer for OMOP concepts. Australian Cancer Data Network. https://github.com/AustralianCancerDataNetwork/omop-emb (faiss branch).

[4] Liu F, Shareghi E, Meng Z, Basaldella M, Collier N. Self-Alignment Pretraining for Biomedical Entity Representations. Proceedings of NAACL-HLT 2021. https://huggingface.co/cambridgeltl/SapBERT-from-PubMedBERT-fulltext

[5] Yuan Z, Zhao Z, Sun H, Li J, Wang F, Yu S. CODER: Knowledge-infused cross-lingual medical term embedding for term normalization. Journal of Biomedical Informatics. 2022;126:103983. https://doi.org/10.1016/j.jbi.2021.103983

[6] Gnecco G, Serrano JC. Hybrid Re-ranking for Biomedical Entity Linking using SapBERT Embeddings: A High-Performance System for BioNNE-L 2025-1. CEUR Workshop Proceedings, Vol. 4038. https://ceur-ws.org/Vol-4038/paper_35.pdf

[7] Elhussein M, et al. KEEP: Integrating Medical Ontologies with Clinical Data for Robust Code Embeddings. Proceedings of the Conference on Health, Inference, and Learning (CHIL), PMLR 2025. https://arxiv.org/abs/2510.05049

[8] Normalizing Health Concepts with Biomedical Embedding and LLMs. Proceedings of the HeaLing Workshop, ACL 2026. https://aclanthology.org/2026.healing-1.15/
