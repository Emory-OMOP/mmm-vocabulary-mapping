# MMM Methodology — Retrieval Comparison Metrics

## Why these metrics

Source-to-Standard concept mapping is a form of **biomedical entity
normalization**: given a surface mention (source code + name), find the
canonical entity (OMOP Standard concept). Standard evaluation for this
task uses ranked retrieval metrics adopted from information retrieval.

## Metrics defined

### Recall@K (= Accuracy@K for single-target tasks)

The proportion of test items for which the correct target appears in
the top-K retrieved candidates. Since each MMM row has one canonical
Standard target (plus an optional alternative), Recall@K is equivalent
to Accuracy@K in this setting:

$$\text{Recall@K} = \frac{1}{N} \sum_{i=1}^{N} \mathbf{1}\left[\text{target}_i \in \text{top-K}_i\right]$$

Where N is the number of queries. The indicator is 1 when the primary
or alternative target_concept_id appears in the top-K results.

**Why this metric**: It is the standard recall-at-rank evaluation in
information retrieval [Salton & McGill, 1983; Manning et al., 2008] and
the dominant metric in recent biomedical entity linking literature
[Liu et al., NAACL 2021 (SapBERT); Sung et al., ACL 2020 (BioSyn);
Yuan et al., JBI 2022 (CODER)]. Within the Emory OHDSI Agent project,
prior work [Smith et al., 2026, internal methods draft
§5.4.2] also reports Acc@1, Acc@5, Acc@10 for embedding model
evaluation — we use the same metrics for methodological consistency.

We report Recall@1 (strict) and Recall@5 (ceiling for LLM picking from
a shortlist), matching the common convention of reporting multiple
cutoffs [Sung et al., 2020].

### Mean Reciprocal Rank (MRR)

$$\text{MRR} = \frac{1}{N} \sum_{i=1}^{N} \frac{1}{\text{rank}_i}$$

Where rank_i is the 1-indexed rank of the first correct target in the
results list, and 1/rank_i is defined as 0 when no correct target
appears in the top-K.

**Why this metric**: MRR summarizes the entire ranking in a single
scalar that emphasizes top-ranked correctness more than Recall@5
[Voorhees, TREC-8 1999]. A result at rank 1 contributes 1.0; rank 2
contributes 0.5; rank 5 contributes 0.2. This matches our intuition
that having the answer at rank 1 is meaningfully better than at rank 5
even though both count equally in Recall@5.

### Mean rank

The arithmetic mean of rank_i for items where the target was found,
as a complement to MRR. A low mean rank with high Recall@K confirms
the retrieved top-K are consistently well-ordered.

## Why a retrieval-only comparison (no LLM in the loop)

Mapping pipelines in this class typically decompose into:

1. **Retrieval**: generate a ranked candidate list per source
2. **Picking**: a reasoner (LLM, rule-based, or human) selects the
   final concept + predicate from that list

**Retrieval-only evaluation** measures an **upper bound** on pipeline
accuracy: if the correct target is not in the top-K retrieved
candidates, no downstream reasoner can recover it. This is the
information-theoretic ceiling, and the right way to isolate retrieval
quality from reasoner quality [Chen et al., 2017 DrQA; Karpukhin et
al., EMNLP 2020 DPR]. The ceiling analysis is cheap and deterministic
and is a prerequisite for meaningful end-to-end evaluation.

After the retrieval comparison identifies the best candidate-generation
strategy, we evaluate end-to-end pipeline accuracy (concept_id + predicate)
in a separate phase that includes the LLM reasoner. That phase is
stochastic (LLM temperature) and we control for it via temperature=0
and fixed seeds where available.

## Determinism notes

All five retrieval configurations tested are effectively deterministic
given a fixed vocabulary snapshot (Feb 2026):

- **R1, R2, R5**: SQL with deterministic ORDER BY (length, then name).
- **R3**: Resolver cascade terminates at the first tier that returns
  high-confidence matches. Embedding tier uses HNSW approximate nearest
  neighbor, but SapBERT inference is no-dropout and DuckDB HNSW returns
  consistent traversal order per query.
- **R4**: Same HNSW-based ANN search, followed by deterministic SQL
  Maps-to join.

HNSW approximation can perturb adjacent rank positions when similarity
scores are within a very small tolerance (<1e-5). These micro-swaps do
not affect whether a target appears in top-5, which is the unit of our
recall evaluation. A single comparison run is therefore sufficient;
multiple runs would be needed only for evaluations involving stochastic
LLM reasoning.

## Terminology note

This analysis is a **retrieval comparison / benchmark**, not an ablation
study in the strict ML sense. An ablation removes components from a
complete system to measure their individual contribution; here we are
comparing distinct candidate-generation strategies against ground truth.
A true ablation study is planned as a separate follow-up once the
end-to-end pipeline is built: the full pipeline (retrieval stack + LLM
reasoning) serves as baseline, and each component is selectively
disabled to measure the degradation in end-to-end Acc@1.

## Scope of this evaluation

**Not in scope for the retrieval comparison:**

- Predicate prediction (exactMatch vs. broadMatch) — this is inherent
  to the LLM-picking step and has no retrieval-only analog.
- Reasoning over the candidate shortlist — LLM's actual selection
  accuracy given top-K candidates.
- Semantic equivalence when multiple concepts could reasonably be
  correct but only one is in the gold standard — the train set provides
  one primary + optional alternative, so we score against both.

**In scope:**

- Per-method recall at ranks 1, 5, (and 10 if we expand top-K).
- Per-method complementarity — which sources find targets that others
  miss. Informs whether union (R5) is worth the noise.
- Mean rank for qualitative ranking quality.

## References

- Cleverdon, C., Kean, M. (1966). *Factors Determining the Performance
  of Indexing Systems*. Cranfield. — Origin of recall/precision for IR.

- Salton, G., McGill, M.J. (1983). *Introduction to Modern Information
  Retrieval*. McGraw-Hill. — Classical IR textbook.

- Manning, C.D., Raghavan, P., Schütze, H. (2008). *Introduction to
  Information Retrieval*. Cambridge University Press. Chapter 8:
  Evaluation in Information Retrieval.

- Voorhees, E.M. (1999). "The TREC-8 Question Answering Track Report."
  *Proceedings of TREC-8.* — Origin of MRR in QA/ranking evaluation.

- Liu, F., Shareghi, E., Meng, Z., Basaldella, M., Collier, N. (2021).
  "Self-Alignment Pretraining for Biomedical Entity Representations."
  *NAACL-HLT 2021.* — SapBERT paper; Acc@1, Acc@5 on medical entity linking.
  https://huggingface.co/cambridgeltl/SapBERT-from-PubMedBERT-fulltext

- Sung, M., Jeon, H., Lee, J., Kang, J. (2020). "Biomedical Entity
  Representations with Synonym Marginalization." *ACL 2020.* — BioSyn;
  Acc@1 / Acc@5 for UMLS normalization.

- Yuan, Z., Zhao, Z., Sun, H., Li, J., Wang, F., Yu, S. (2022). "CODER:
  Knowledge-infused cross-lingual medical term embedding for term
  normalization." *JBI* 126:103983.

- Chen, D., Fisch, A., Weston, J., Bordes, A. (2017). "Reading Wikipedia
  to Answer Open-Domain Questions." *ACL 2017.* — Established the
  retriever/reader separation in open-domain QA; ceiling analysis.

- Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen,
  D., Yih, W. (2020). "Dense Passage Retrieval for Open-Domain Question
  Answering." *EMNLP 2020.* — Retrieval-first pipeline evaluation with
  Recall@K at multiple cutoffs; standard in modern RAG evaluation.

- Smith, D., Marquez, J., Rhodes, J., Zhang, X., Budiman, B. (2026).
  "Graph-Augmented Vocabulary Tools and Semantic Concept Resolution for
  an MCP-Native OHDSI Agent." Working methods draft. Internal reference.
  See §5.4.2 for the prior Acc@K / MRR evaluation protocol this analysis
  extends.

- Gnecco, G., Serrano, J.C. (2025). "Hybrid Re-ranking for Biomedical
  Entity Linking using SapBERT Embeddings: A High-Performance System
  for BioNNE-L 2025-1." CEUR-WS Vol. 4038.
  https://ceur-ws.org/Vol-4038/paper_35.pdf — Acc@1 for BioNNE-L 2025
  biomedical entity linking competition.

- Cormack, G.V., Clarke, C.L.A., Büttcher, S. (2009). "Reciprocal Rank
  Fusion Outperforms Condorcet and Individual Rank Learning Methods."
  *SIGIR 2009.* — Cited for R5 candidate combination approach.
