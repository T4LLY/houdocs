# Documentation Search Specification

## Purpose

Define the version-local documentation search index, its four search domains, and the `houdocs search <query> [--domain ...]` contract.

## Requirements

### Requirement: Build search state during init

`houdocs init` SHALL build the selected version's `search.db` as rebuildable derived data with `node`, `hom`, `vex`, and `document` namespaces.

#### Scenario: First search indexing run
- **WHEN** common and specialized documentation indexes exist and the version has no search index
- **THEN** node-document sections are indexed in `node`
- **AND** general sections outside Node, HOM, and VEX are indexed in `document`
- **AND** each directly readable HOM symbol is indexed as one `hom` search entry
- **AND** each VEX function is indexed as one `vex` search entry

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

### Requirement: Expose only domain selection as a public search control

The public command SHALL be `houdocs search <query> [--domain node|vex|hom|document]`. It SHALL NOT expose public top-k, rebuild, embedding-profile, or ranking controls.

#### Scenario: Search initialized docs without a domain
- **WHEN** the caller runs `houdocs search "packed primitive"`
- **THEN** HouDocs searches all four domains using the configured internal defaults

#### Scenario: Search one domain
- **WHEN** the caller runs `houdocs search "nearest surface" --domain vex`
- **THEN** only VEX function search entries participate in ranking

### Requirement: Search results expose only compact navigation metadata

The top-level search result SHALL contain only `hits`. Each hit SHALL return `path`, `kind`, and `score`. `path` SHALL combine the document title and heading hierarchy without repeating an identical adjacent title. Search SHALL NOT return the query, section body text, internal section IDs, source paths, anchors, or duplicated heading fields.

#### Scenario: Return one search hit
- **WHEN** a documentation section matches the query
- **THEN** the hit contains only `path`, `kind`, and `score`
- **AND** `path` preserves the document and heading hierarchy without duplicated adjacent titles
- **AND** the response contains no `query`, `text`, `section_id`, `relative_path`, `anchor`, `document`, `heading`, or `heading_path` field

### Requirement: Bound SQLite lookup parameter counts

Search indexing SHALL split large entry-ID and content-hash lookup sets into bounded batches before constructing SQLite `IN` clauses. The batching SHALL NOT change the set of matched entries or the resulting search index.

#### Scenario: Initializing a documentation set larger than SQLite's variable limit
- **WHEN** `houdocs init` needs to inspect more search entry IDs than SQLite accepts in one statement
- **THEN** HouDocs queries those IDs in bounded batches
- **AND** indexing continues without a `too many SQL variables` failure

### Requirement: Embedding work is bounded by source document

Search indexing SHALL group changed search entries by their source document before submitting them to the embedding backend rather than using one version-wide batch. This batching SHALL NOT change section identity, cache reuse, progress totals, or search results.

#### Scenario: Multiple documents require embeddings
- **WHEN** changed sections from multiple documentation pages require embeddings
- **THEN** each backend upsert contains sections from only one document
- **AND** the progress total still represents all uncached embeddings for the init
