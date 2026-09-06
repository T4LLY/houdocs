# Documentation Search Specification

## Purpose

Define the version-local documentation search index and the minimal `houdocs search <query>` contract.

## Requirements

### Requirement: Build search state during init

`houdocs init` SHALL build or incrementally update the selected version's `search.db` from the current common documentation sections. Search state SHALL be rebuildable derived data and SHALL use only the `docs` namespace.

#### Scenario: First search indexing run
- **WHEN** common documentation sections exist and the version has no search index
- **THEN** every current section is added to `search.db`
- **AND** each search entry references its section ID

#### Scenario: Reinitialize unchanged sections
- **WHEN** a section content hash and embedding profile are unchanged
- **THEN** its search entry is skipped
- **AND** its cached embedding remains reusable

#### Scenario: Embedding profile changes
- **WHEN** the configured documentation embedding profile changes
- **THEN** current sections are reindexed for the new profile even if their text is unchanged

### Requirement: Preserve the existing hybrid ranking algorithm

Documentation search SHALL use SQLite FTS lexical ranking plus dense Model2Vec embeddings stored through sqlite-vec and combine the two ranked lists with reciprocal rank fusion. The configurable RRF `k`, candidate multiplier, and candidate minimum SHALL retain the existing Houbridge defaults unless configuration overrides them.

#### Scenario: Result appears in both dense and lexical rankings
- **WHEN** a section ranks in both candidate lists
- **THEN** its final score includes both reciprocal-rank contributions

### Requirement: Keep the public search CLI query-only

The public command SHALL be `houdocs search <query>` with no public domain, top-k, rebuild, embedding-profile, or ranking options.

#### Scenario: Search initialized docs
- **WHEN** the caller runs `houdocs search "packed primitive"`
- **THEN** HouDocs searches the effective version's docs namespace using the configured internal defaults

### Requirement: Search results do not return section bodies

Each hit SHALL return `section_id`, `score`, `document`, `heading`, `heading_path`, `kind`, `relative_path`, and `anchor`. Search SHALL NOT return section body text or Houbridge Resource identifiers.

#### Scenario: Return one search hit
- **WHEN** a documentation section matches the query
- **THEN** the hit identifies the section and document metadata
- **AND** the hit contains no `text` or `resource` field

### Requirement: Bound SQLite lookup parameter counts

Search indexing SHALL split large entry-ID and content-hash lookup sets into bounded batches before constructing SQLite `IN` clauses. The batching SHALL NOT change the set of matched entries or the resulting search index.

#### Scenario: Initializing a documentation set larger than SQLite's variable limit
- **WHEN** `houdocs init` needs to inspect more search entry IDs than SQLite accepts in one statement
- **THEN** HouDocs queries those IDs in bounded batches
- **AND** indexing continues without a `too many SQL variables` failure

### Requirement: Embedding work is bounded by document

Search indexing SHALL submit changed documentation sections to the embedding backend one document at a time rather than as one version-wide batch. This batching SHALL NOT change section identity, cache reuse, progress totals, or search results.

#### Scenario: Multiple documents require embeddings
- **WHEN** changed sections from multiple documentation pages require embeddings
- **THEN** each backend upsert contains sections from only one document
- **AND** the progress total still represents all uncached embeddings for the init
