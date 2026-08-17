# Brand Atlas Knowledge Graph Optimization Technical Plan

> Version: 0.1.0
> Date: 2026-08-12
> Scope: L1/L2/L3 knowledge graph construction optimization. Dynamic update, recommendation, and downstream GraphRAG applications are out of scope for this phase.

## 1. Executive Summary

The current Brand Atlas knowledge graph already follows an ontology-guided, schema-first, assertion-centric property graph approach:

```text
L1 ontology/schema definitions
-> L2 industry knowledge construction
-> L3 brand knowledge construction
-> PostgreSQL authoritative store
-> Neo4j rebuildable graph projection
```

The current MVP is technically sound, but the extraction and validation flow still relies too heavily on LLM extraction. Entity resolution is mostly exact-name based, and evidence verification is currently string-match based. This plan upgrades the construction pipeline with a medium-cost architecture:

```text
Document parsing
-> rule/dictionary/small-model candidate generation
-> LLM structured extraction for hard cases
-> strict schema and ontology validation
-> embedding + blocking entity resolution
-> semantic evidence verification
-> PostgreSQL + pgvector authoritative storage
-> Neo4j graph projection
```

Primary goals:

- Improve extraction efficiency by reducing unnecessary LLM calls.
- Improve cost-performance by routing simple facts to rules and small models.
- Improve graph quality through stricter schema validation, semantic entity resolution, and evidence support judgment.
- Preserve the existing PostgreSQL-as-authority and Neo4j-as-projection architecture.

## 2. Current Architecture Assessment

### 2.1 Current Strengths

The project already has the right high-level architecture:

- L1 ontology definitions are stored in YAML and registered into PostgreSQL.
- L2 and L3 pipelines are separated by industry-level and brand-level responsibilities.
- L3 uses an assertion-centric model to preserve statement text, evidence, status, confidence, access level, and versioning.
- PostgreSQL is treated as the authoritative runtime store.
- Neo4j is used as a rebuildable graph query projection, not as the write authority.
- Candidate data and active data are separated, which allows review and promotion.

### 2.2 Current Gaps

| Area | Current State | Main Gap |
|---|---|---|
| Document parsing | Markdown/HTML/plain text rule parser | Weak support for PDF, PPT, tables, layout, and scanned docs |
| Candidate extraction | LLM extracts entities, relations, and statements directly | LLM cost is high and output stability depends on prompt quality |
| Output validation | Prompt-level ontology whitelist | Needs strict structured output and schema validation |
| Entity resolution | Exact canonical-name deduplication | Cannot robustly handle aliases, abbreviations, product versions, and same-name conflicts |
| Evidence verification | String containment/direct-partial heuristic | Cannot judge semantic support, contradiction, or overclaiming |
| Vector retrieval | Not yet present in authoritative store | Entity resolution and evidence recall lack semantic search |
| Workflow reliability | Pipeline works step by step | Needs checkpointing, transaction boundaries, and model/prompt version tracking |

## 3. Target Architecture

```text
Original files / crawled pages
        |
        v
Source registration + original file gate
        |
        v
Enhanced document parsing
        |
        v
Evidence span generation
        |
        v
Rule / dictionary / small-model candidate generation
        |
        v
LLM structured extraction for hard spans and unresolved candidates
        |
        v
Pydantic / JSON Schema validation
        |
        v
Ontology and business-rule validation
        |
        v
Embedding + blocking entity resolution
        |
        v
Semantic evidence verification
        |
        v
Review promotion
        |
        v
PostgreSQL authoritative store + pgvector
        |
        v
Neo4j graph projection
```

This is not a replacement of the current design. It is an enhancement of the existing L3 pipeline, with the most important changes inserted between `semantic_chunking`, `candidate_extraction`, `entity_resolution`, and `evidence_verification`.

## 4. Recommended Technology Placement

### 4.1 Document Parsing Layer

Current location:

- `runtime/l3/pipelines/layout_aware_parsing.py`
- `runtime/l3/pipelines/semantic_chunking.py`

Recommended enhancement:

Add an enhanced parser adapter before the current `layout_aware_parsing` output is written to `document_chunk`.

Recommended tools:

| Input Type | Recommended Technology | Role |
|---|---|---|
| Markdown/Text | Existing parser | Keep as default low-cost path |
| HTML/Web pages | Trafilatura + Playwright fallback | Extract clean main content and preserve source URL |
| PDF | Docling or PyMuPDF | Preserve page, heading, table, and layout metadata |
| DOCX/PPTX/XLSX | Unstructured or python-docx/python-pptx/openpyxl | Preserve paragraphs, slides, tables, and sheet structure |
| Scanned PDF/Image | OCR fallback such as PaddleOCR | Use only when text extraction fails |

Recommended new module:

```text
runtime/l3/parsers/
  __init__.py
  document_parser.py
  markdown_parser.py
  html_parser.py
  pdf_parser.py
  office_parser.py
```

Recommended output contract:

```json
{
  "document_id": "doc_xxx",
  "blocks": [
    {
      "block_type": "heading|paragraph|table|list|image_caption",
      "heading_path": "Product > Security",
      "text": "...",
      "page": 3,
      "source_locator": "p.3/table.1",
      "access_level": "internal"
    }
  ]
}
```

Expected benefit:

- Better extraction quality because LLM and rule engines receive cleaner evidence spans.
- Better traceability because evidence can carry page/table/section metadata.

### 4.2 Rule / Dictionary / Small-Model Candidate Layer

Current location:

- Currently absent.
- Candidate extraction starts directly in `runtime/l3/pipelines/candidate_extraction.py`.

Recommended insertion point:

```text
semantic_chunking
-> candidate_pre_extraction
-> candidate_extraction
```

Recommended new pipeline:

```text
runtime/l3/pipelines/candidate_pre_extraction.py
```

Recommended supporting files:

```text
brand_knowledge/rules/
  entity_patterns.yaml
  relation_patterns.yaml
  metric_patterns.yaml
  certification_patterns.yaml

brand_knowledge/dictionaries/
  product_terms.yaml
  organization_suffixes.yaml
  capability_terms.yaml
  certification_terms.yaml
```

Recommended techniques:

| Candidate Type | Method | Example |
|---|---|---|
| URL/domain/email/phone | Regex | official domain, contact information |
| Date/version/price/SLA/percentage/ROI | Regex + unit normalization | `V2.1`, `99.9%`, `P0 15分钟` |
| Organization | Dictionary + suffix rules + NER | `有限公司`, `Inc.`, `Group` |
| Product | Product dictionary + page title/heading | product detail pages |
| Certification | Certification dictionary + regex | ISO 27001, 等保三级 |
| Brand offers Product | DOM/page structure + relation template | brand product pages |
| Product has Capability | Capability dictionary + local context | feature sections |

Recommended libraries:

- `regex` for deterministic extraction.
- `pyahocorasick` or `FlashText` for high-speed dictionary matching.
- HanLP, PaddleNLP, spaCy, or GLiNER for optional small-model NER.

Recommended candidate table:

```sql
CREATE TABLE extraction_candidate (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL,
  brand_id UUID NOT NULL,
  document_id UUID,
  chunk_id UUID,
  candidate_type VARCHAR(40) NOT NULL,
  candidate_payload JSONB NOT NULL,
  generator VARCHAR(100) NOT NULL,
  confidence NUMERIC(4,3),
  status VARCHAR(20) NOT NULL DEFAULT 'candidate',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Expected benefit:

- Simple facts no longer require LLM.
- LLM receives structured hints instead of raw text only.
- Candidate extraction becomes more explainable and cheaper.

### 4.3 LLM Structured Extraction Layer

Current location:

- `runtime/extract.py`
- `runtime/l3/pipelines/candidate_extraction.py`

Current behavior:

```text
evidence span text
-> LLM prompt
-> JSON parse
-> entity / relation / assertion insert
```

Recommended enhancement:

Use strict structured output plus local validation:

```text
LLM structured output
-> Pydantic validation
-> ontology validation
-> candidate insertion
```

Recommended technologies:

| Need | Recommended Technology |
|---|---|
| Strict Python models | Pydantic v2 |
| Portable schema | JSON Schema |
| Provider-level schema enforcement | OpenAI Structured Outputs or equivalent |
| Retry/repair | Validation error driven re-prompt |

Recommended new module:

```text
runtime/extraction_schema.py
runtime/ontology_validator.py
```

Recommended validation rules:

- Entity type must exist in L1/L3 ontology.
- Relation type must exist in ontology.
- Relation domain/range must be valid.
- Entity references in relations must exist in the same extraction result or existing DB.
- Confidence must be in `[0, 1]`.
- Statement class must be one of `fact`, `claim`, `observation`, `inference`.
- High-risk claim types must require evidence and review.

Recommended flow change in `candidate_extraction.py`:

```text
Load evidence span
-> Load pre-extraction candidates
-> Call LLM with allowed ontology + candidates
-> Validate with Pydantic
-> Validate with ontology validator
-> Insert entities/relations/assertions as candidate rows
```

Expected benefit:

- Fewer malformed outputs.
- Fewer invented entity/relation types.
- Cleaner relation semantics before data reaches PostgreSQL and Neo4j.

### 4.4 Entity Resolution Layer: Blocking + Embedding

Current location:

- `runtime/l3/pipelines/entity_resolution.py`

Current behavior:

```text
tenant_id + owner_brand + entity_type + canonical_name exact match
```

Recommended target behavior:

```text
Normalize entity text
-> blocking candidate retrieval
-> embedding similarity
-> rule-based feature scoring
-> auto merge / review / create
```

Recommended blocking features:

| Feature | Purpose |
|---|---|
| `tenant_id` | Prevent cross-tenant leakage |
| `owner_brand` | Prefer brand-local candidates |
| `entity_type` | Avoid comparing product with organization |
| normalized name | Remove whitespace, punctuation, full-width/half-width differences |
| aliases | Match known brand/product aliases |
| source domain | Same official domain raises confidence |
| product version | Avoid merging product and version incorrectly |
| language/pinyin/slug | Improve Chinese-English matching |

Recommended embedding models:

| Option | Recommendation |
|---|---|
| `bge-m3` | Best medium-cost local default for Chinese-English mixed data |
| `bge-large-zh-v1.5` | Good if data is mostly Chinese |
| `multilingual-e5-large` | Good multilingual alternative |
| OpenAI embedding model | Good managed API option if deployment simplicity matters more than local control |

Recommended similarity scoring:

```text
final_score =
  0.35 * name_similarity
+ 0.30 * embedding_similarity
+ 0.15 * alias_match
+ 0.10 * source_overlap
+ 0.10 * type_compatibility
```

Recommended decision thresholds:

```text
>= 0.90       auto merge
0.75 - 0.90  review_queue
< 0.75       create new entity
```

High-risk entity types should not be auto-merged unless confidence is extremely high:

```text
brand
organization
product
product_version
certification
```

Recommended new tables:

```text
entity_embedding
entity_resolution_candidate
```

Expected benefit:

- Better alias handling.
- Lower duplicate entity count.
- Lower risk of merging different products or organizations incorrectly.

### 4.5 Semantic Evidence Verification Layer

Current location:

- `runtime/l3/pipelines/evidence_verification.py`

Current behavior:

```text
quote in statement or statement in quote -> direct
else -> partial
```

Recommended target behavior:

```text
evidence span + assertion statement
-> semantic verifier
-> direct_support / partial_support / insufficient / contradicted
-> confidence + reason + unsupported parts
```

Recommended model routing:

| Assertion Risk | Recommended Verifier |
|---|---|
| Low risk | Reranker/cross-encoder relevance model |
| Medium risk | NLI model or cross-encoder + rule checks |
| High risk | LLM verifier + human review |

Recommended models:

| Model/Family | Role |
|---|---|
| `bge-reranker-v2-m3` | Chinese-English evidence relevance scoring |
| Sentence Transformers CrossEncoder | General evidence-statement matching |
| XLM-R / mDeBERTa NLI | Entailment / neutral / contradiction |
| LLM verifier | High-risk claims, ROI, certification, public output |

Recommended verifier output:

```json
{
  "support_status": "direct_support",
  "confidence": 0.86,
  "support_reason": "The evidence explicitly states that the product supports multi-entity consolidation.",
  "unsupported_parts": [],
  "verifier_version": "semantic_verifier.v1"
}
```

Recommended high-risk categories:

- Certification and compliance claims.
- Quantified ROI or performance claims.
- "First", "only", "best", "leading" claims.
- Customer case results.
- SLA and delivery commitments.
- Competitor comparisons.
- Public content claims.

Expected benefit:

- Reduces unsupported assertions entering active graph.
- Makes review work more focused.
- Makes downstream GraphRAG and reporting more trustworthy.

### 4.6 PostgreSQL + pgvector Layer

Current location:

- `runtime/migrations/`
- `brand_knowledge/database/brand_l3_migration.sql`
- `runtime/db.py`

Current behavior:

PostgreSQL stores authoritative entities, relations, statements, assertions, evidence, review state, tenant isolation, and snapshots.

Recommended enhancement:

Add pgvector to the authoritative PostgreSQL store.

Recommended new migration:

```text
runtime/migrations/vector_migration.sql
```

Recommended tables:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS entity_embedding (
  entity_id UUID PRIMARY KEY REFERENCES entity(id),
  tenant_id UUID,
  embedding_model TEXT NOT NULL,
  embedding vector(1024) NOT NULL,
  embedded_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evidence_embedding (
  evidence_id UUID PRIMARY KEY REFERENCES evidence(id),
  tenant_id UUID,
  embedding_model TEXT NOT NULL,
  embedding vector(1024) NOT NULL,
  embedded_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assertion_embedding (
  assertion_id UUID PRIMARY KEY REFERENCES assertion(id),
  tenant_id UUID,
  embedding_model TEXT NOT NULL,
  embedding vector(1024) NOT NULL,
  embedded_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

If a non-1024-dimension model is selected, the vector dimension must match the model. The selected dimension should be defined in config and migration together.

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_entity_embedding_hnsw
ON entity_embedding USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_evidence_embedding_hnsw
ON evidence_embedding USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_assertion_embedding_hnsw
ON assertion_embedding USING hnsw (embedding vector_cosine_ops);
```

Recommended use cases:

- Entity resolution candidate retrieval.
- Evidence recall for assertion verification.
- Similar assertion detection.
- Future GraphRAG hybrid retrieval.

Expected benefit:

- Adds semantic search without introducing a separate vector database.
- Keeps permissions, tenant boundaries, and audit metadata close to the authoritative data.

### 4.7 Neo4j Projection Layer

Current location:

- `runtime/neo4j/projection.py`
- `runtime/neo4j/cypher_init.cypher`
- `runtime/neo4j/consistency.py`

Recommended approach:

Keep the current design:

```text
PostgreSQL is authoritative.
Neo4j is rebuildable.
Only active, validated graph data should be projected.
```

Recommended enhancement:

- Do not project low-confidence candidates.
- Project semantic verifier status and confidence onto assertion nodes/edges.
- Project `snapshot_id`, `tenant_id`, `brand_id`, `access_level`, and `publication_status`.
- Keep parameterized Cypher and whitelist-based labels.

Expected benefit:

- Neo4j remains clean and query-oriented.
- Bad candidate data stays in PostgreSQL review flow instead of polluting graph traversal.

## 5. Proposed Pipeline Changes

### 5.1 Current L3 Pipeline

```text
source_registration
-> original_file_gate
-> layout_aware_parsing
-> semantic_chunking
-> candidate_extraction
-> entity_resolution
-> l2_mapping
-> assertion_classification
-> evidence_verification
-> review_promotion
```

### 5.2 Optimized L3 Pipeline

```text
source_registration
-> original_file_gate
-> enhanced_layout_parsing
-> semantic_chunking
-> candidate_pre_extraction
-> candidate_extraction_with_schema_validation
-> ontology_validation
-> entity_resolution_with_embedding
-> l2_mapping
-> assertion_classification
-> semantic_evidence_verification
-> review_promotion
-> embedding_index_update
-> neo4j_projection
```

### 5.3 Minimal Code Changes by Phase

Phase 1: Strict extraction contracts

- Add `runtime/extraction_schema.py`.
- Add Pydantic models for extracted entities, relations, statements.
- Modify `runtime/extract.py` to validate LLM output.
- Add ontology domain/range validation before DB insert.

Phase 2: Candidate pre-extraction

- Add `runtime/l3/pipelines/candidate_pre_extraction.py`.
- Add rule and dictionary YAML files.
- Add `extraction_candidate` table.
- Modify `candidate_extraction.py` to read pre-extracted candidates.

Phase 3: pgvector and embeddings

- Add `runtime/migrations/vector_migration.sql`.
- Add embedding client module.
- Add `entity_embedding`, `evidence_embedding`, `assertion_embedding`.
- Add embedding generation after entity/evidence/assertion creation.

Phase 4: Entity resolution upgrade

- Replace exact-only logic in `entity_resolution.py` with blocking + embedding retrieval + scoring.
- Keep exact match as the first and cheapest rule.
- Send ambiguous merges to `review_queue`.

Phase 5: Semantic evidence verification

- Replace string-only support checks in `evidence_verification.py`.
- Add reranker/NLI/LLM verifier routing.
- Store support confidence, reason, unsupported parts, and verifier version.

## 6. Recommended Model Strategy

### 6.1 Default Medium-Cost Stack

| Layer | Recommended Choice |
|---|---|
| LLM extraction | Existing LLM provider with structured output |
| Local embedding | `bge-m3` |
| Reranker | `bge-reranker-v2-m3` |
| Optional Chinese NER | HanLP or PaddleNLP |
| Python validation | Pydantic v2 |
| Vector store | PostgreSQL + pgvector |
| Graph projection | Existing Neo4j projection |

### 6.2 When to Use LLM

LLM should be used for:

- Complex relation extraction.
- Capability-to-L2 mapping when dictionary rules are insufficient.
- Assertion classification.
- Ambiguous product/brand/org distinctions.
- High-risk evidence verification.
- Conflict explanation.

LLM should not be the first tool for:

- Dates, versions, prices, URLs, domains, emails, phone numbers.
- Known product names.
- Known certification names.
- Simple dictionary capabilities.
- Exact entity alias lookup.

## 7. Cost and Quality Control

### 7.1 Cost Controls

- Cache LLM extraction results by `chunk_id + prompt_version + model_version`.
- Cache embeddings by `entity/evidence/assertion content hash + embedding_model`.
- Only call LLM on spans with useful candidates or high information density.
- Skip repeated boilerplate spans such as footer, navigation, cookie policy, and legal template text.
- Use small reranker/NLI models before expensive LLM verification.

### 7.2 Quality Controls

- Every active assertion must have evidence.
- Every public assertion must pass semantic evidence verification.
- High-risk claims must enter review unless explicitly approved.
- Entity merges for brand/organization/product/certification require stricter thresholds.
- Ontology domain/range violations must block promotion.
- Neo4j consistency checks should compare active PostgreSQL counts and projected graph counts.

## 8. Acceptance Criteria

The optimization is successful when:

- LLM calls per document decrease by at least 40% without reducing accepted assertion count.
- Entity duplicate rate decreases after embedding-based resolution.
- Public assertions have 100% evidence links.
- Evidence verification distinguishes direct support, partial support, insufficient support, and contradiction.
- PostgreSQL can still fully rebuild Neo4j.
- Candidate data does not pollute active graph projection.
- A new brand can be onboarded without modifying pipeline code.

## 9. Recommended Implementation Order

1. Add strict LLM schema validation.
2. Add rule/dictionary candidate pre-extraction.
3. Add pgvector and embedding tables.
4. Upgrade entity resolution to blocking + embedding scoring.
5. Upgrade evidence verification to semantic support judgment.
6. Add metrics dashboards for cost, acceptance rate, duplicate rate, and verification outcomes.

This order keeps risk low. Each phase produces measurable value and does not require replacing the current PostgreSQL + Neo4j architecture.

## 10. Installation and Model Download Plan

This section lists the recommended libraries and small models for the medium-cost implementation. The project should not install every optional dependency at once. Start with the required baseline, then add optional parsers and local models as needed.

### 10.1 Required Baseline Libraries

These dependencies are recommended for the first optimization phase.

```text
pydantic>=2.0
jsonschema>=4.0
pyahocorasick>=2.0
regex>=2024.0.0
pgvector>=0.3.0
sentence-transformers>=3.0.0
numpy>=1.26
```

Purpose:

| Library | Used For | Pipeline Position |
|---|---|---|
| `pydantic` | Strict LLM output validation | `candidate_extraction` |
| `jsonschema` | Portable schema validation | `candidate_extraction`, `ontology_validation` |
| `pyahocorasick` | Fast dictionary matching | `candidate_pre_extraction` |
| `regex` | Robust rule extraction | `candidate_pre_extraction` |
| `pgvector` | PostgreSQL vector operations from Python | embedding storage/query |
| `sentence-transformers` | Local embedding and reranker model runtime | entity resolution, evidence verification |
| `numpy` | Vector and scoring utilities | entity resolution |

Recommended placement:

```text
Knowledge_Graph/runtime/requirements.txt
```

### 10.2 Optional Document Parsing Libraries

Install these only when the corresponding source type is needed.

```text
docling
trafilatura
beautifulsoup4
lxml
pymupdf
python-docx
python-pptx
openpyxl
```

Purpose:

| Library | Used For | When Needed |
|---|---|---|
| `docling` | PDF/Office layout-aware parsing | PDF, DOCX, PPTX-heavy brand materials |
| `trafilatura` | Clean web page text extraction | Crawled official websites |
| `beautifulsoup4` + `lxml` | HTML structure extraction | Product pages, FAQ pages |
| `pymupdf` | Lightweight PDF text/page extraction | Simple PDFs |
| `python-docx` | DOCX structure extraction | Word documents |
| `python-pptx` | PPTX slide extraction | Product decks |
| `openpyxl` | XLSX table extraction | Pricing, feature, parameter tables |

Recommended placement:

```text
Knowledge_Graph/runtime/requirements-parsing.txt
```

### 10.3 Optional Chinese NLP Libraries

Use these only if rule/dictionary extraction is not enough for organization, product, and capability candidate generation.

```text
hanlp
paddlenlp
spacy
gliner
```

Recommendation:

- Start without these libraries.
- Add `HanLP` or `PaddleNLP` if Chinese NER quality becomes a bottleneck.
- Add `GLiNER` if flexible schema-based entity extraction is needed without calling a large LLM.

**Implementation note (NER small-model layer):** PaddleNLP is now wired in as the
optional small-model NER layer in the L3 candidate chain. See
`runtime/ner_client.py` (provider abstraction mirroring `embeddings.py`) and its
integration in `runtime/l3/pipelines/candidate_pre_extraction.py` (a
`_ner_entities` layer injected via `pre_extract(text, ner_client)` after the
rule/dictionary extractors). It emits `extraction_candidate` rows tagged
`generator="paddlenlp:ner:<type>"`. The dependency (`paddlenlp` + `paddlepaddle`,
added to `runtime/requirements-local-models.txt`) is strictly optional: if not
installed (or a model fails to initialize — PaddlePaddle can be finicky on some
Python/Windows combos), the layer degrades to empty and the L2/L3 pipelines run
untouched. Configuration lives under the `"ner"` key of
`runtime/config/model-config.local.json` (`enabled`/`provider`/`model`/`schema`),
toggleable at the CLI with `--skip-ner`.

**Runtime-verified notes (2026-08-13, Windows/Py3.12):**
- Model: `uie-base` (UIE ERNIE). paddlenlp 2.6's `information_extraction`
  Taskflow does **not** accept `uie-base-zh` — valid Catalina names are
  `uie-base` / `uie-medium` / `uie-mini` / `uie-micro` / `uie-nano`.
- **Paddle compatibility:** the task uses the static-graph export
  (`static/inference.pdmodel`). This export **fails under paddlepaddle 3.x** but
  succeeds under **paddlepaddle 2.6.x**. Pin `paddlepaddle==2.6.2` +
  `paddlenlp==2.6.1` as a working pair (both have cp312 Windows wheels).
- **Chinese schema required:** UIE is a Chinese model — it returns empty spans
  when given **English** schema labels. The NER client therefore translates the
  config's English schema to Chinese (`公司`/`产品`/`能力`/`认证`) before the call
  and maps UIE labels back to English `candidate_type`.
- Span cleaning (`_clean_span`) trims dangling/unbalanced brackets UIE sometimes
  leaves at a span boundary while preserving balanced parenthesized spans.

### 10.4 Recommended Local Embedding and Reranker Models

Default local model stack:

| Model | Purpose | Recommended Use |
|---|---|---|
| `BAAI/bge-m3` | Embedding | Entity resolution, evidence retrieval, future hybrid search |
| `BAAI/bge-reranker-v2-m3` | Reranking / semantic evidence relevance | Evidence verifier, candidate support scoring |

Recommended download method:

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"
```

Recommended local cache behavior:

- Models are downloaded to the Hugging Face cache by default.
- In production, set an explicit model cache directory through environment configuration.
- Record model name and version in the database with each embedding or verifier result.

Recommended config fields:

```json
{
  "embedding": {
    "provider": "local",
    "model": "BAAI/bge-m3",
    "dimension": 1024
  },
  "reranker": {
    "provider": "local",
    "model": "BAAI/bge-reranker-v2-m3"
  }
}
```

Recommended placement:

```text
Knowledge_Graph/runtime/config/model-config.example.json
Knowledge_Graph/runtime/config/model-config.local.json
```

### 10.5 Managed API Alternative

If local model deployment is not desired, use a managed embedding API instead of downloading local embedding models.

Recommended use:

| Component | Local Option | Managed API Option |
|---|---|---|
| Embedding | `BAAI/bge-m3` | OpenAI embedding model or equivalent |
| Evidence verifier | `bge-reranker-v2-m3` + NLI | LLM verifier with structured output |
| LLM extraction | Existing LLM client | Existing LLM client with strict schema |

Tradeoff:

- Local models reduce unit cost and improve data control.
- Managed APIs reduce deployment complexity and usually provide more stable operations.

### 10.6 PostgreSQL Extension Requirement

The database needs the `pgvector` extension installed in PostgreSQL.

Migration requirement:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Docker/PostgreSQL note:

- The current PostgreSQL image must include pgvector, or the runtime Docker image should be changed to a pgvector-enabled PostgreSQL image.
- The Python package `pgvector` is not enough by itself; the PostgreSQL server also needs the extension.

### 10.7 Suggested Dependency Files

Recommended split:

```text
Knowledge_Graph/runtime/requirements.txt
Knowledge_Graph/runtime/requirements-parsing.txt
Knowledge_Graph/runtime/requirements-local-models.txt
```

Suggested contents:

```text
# requirements-local-models.txt
sentence-transformers>=3.0.0
torch
transformers
accelerate
```

Use `torch` CPU by default for MVP. Move to GPU only when throughput requires it.

### 10.8 Minimal First Installation

For the first implementation phase, install only:

```text
pydantic
jsonschema
regex
pyahocorasick
pgvector
```

Then add local embedding/reranker models in the second phase:

```text
sentence-transformers
torch
transformers
```

This avoids turning the first optimization step into a heavy ML deployment project.
