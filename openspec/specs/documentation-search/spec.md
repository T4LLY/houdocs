# Documentation Search Specification

## Purpose

Define the version-local documentation search index, its four search domains, and the `houdocs search <query> [--domain ...]` contract.

## Requirements

### Requirement: Build fresh search state during init

`houdocs init` SHALL build the selected version's `search.db` as rebuildable derived data with `node`, `hom`, `vex`, and `document` namespaces. A normal init SHALL build from a fresh staged search database and SHALL NOT use the previous generated search entries as incremental input.

#### Scenario: Build the search index
- **WHEN** common and specialized documentation indexes exist
- **THEN** node-document sections are indexed in `node`
- **AND** general sections outside Node, HOM, and VEX are indexed in `document`
- **AND** each directly readable HOM symbol is indexed as one `hom` search entry
- **AND** each VEX function is indexed as one `vex` search entry

#### Scenario: Reinitialize unchanged sections
- **WHEN** a version is initialized again with unchanged source documentation
- **THEN** all current search entries are written into the fresh staged search database
- **AND** no previous search-entry state is consulted to skip them

### Requirement: Reuse duplicate embeddings within the staged build

Within one staged search build, HouDocs SHALL reuse an embedding when the same content hash has already been embedded for the configured documentation embedding profile. Duplicate content SHALL NOT require another model invocation. The embedding data is derived acceleration state and SHALL NOT make a previous completed search index an input to a later normal init.

#### Scenario: Two entries have identical searchable content
- **WHEN** one search entry has already produced an embedding and a later entry in the same staged build has the same content hash
- **THEN** the existing embedding is reused for the later entry
- **AND** the embedding model is not invoked again for that content

### Requirement: Support one configured embedding profile while retaining an extension point

The supported public init and search workflow SHALL use one configured documentation embedding profile for the generated search index. Multiple concurrently active embedding profiles SHALL NOT be a supported public feature. Internal profile identifiers, profile-specific vector storage, and backend mechanisms MAY remain as extension points for introducing multi-profile support in the future.

#### Scenario: Initialize with the configured documentation profile
- **WHEN** normal initialization builds searchable entries
- **THEN** all generated entries use the configured documentation embedding profile
- **AND** no public control selects multiple active profiles

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

The top-level search result SHALL contain only `hits`. Each hit SHALL return `path`, `kind`, `score`, and `tokens`. `path` SHALL combine the document title and heading hierarchy without repeating an identical adjacent title. Search SHALL NOT return the query, section body text, internal section IDs, source paths, anchors, or duplicated heading fields.

#### Scenario: Return one search hit
- **WHEN** a documentation section matches the query
- **THEN** the hit contains only `path`, `kind`, `score`, and `tokens`
- **AND** `path` preserves the document and heading hierarchy without duplicated adjacent titles
- **AND** the response contains no `query`, `text`, `section_id`, `relative_path`, `anchor`, `document`, `heading`, or `heading_path` field

### Requirement: Search results expose OpenAI token cost

Each search entry SHALL store the token count of the text returned when that entry is read. Token counts SHALL use OpenAI `o200k_base` tokenization and SHALL be computed during search indexing, not during each search request.

#### Scenario: Index a searchable unit
- **WHEN** a document section, HOM symbol, or VEX function is added to the search index
- **THEN** HouDocs computes its readable text token count with `o200k_base`
- **AND** stores that count in the search entry

#### Scenario: Return one search hit
- **WHEN** a stored search entry matches a query
- **THEN** the hit returns the stored count as `tokens`
- **AND** the search request does not tokenize the article again

### Requirement: Bound SQLite lookup parameter counts

Search storage SHALL split large entry-ID and content-hash lookup sets into bounded batches before constructing SQLite `IN` clauses. The batching SHALL NOT change the set of matched entries or the resulting search index.

#### Scenario: Initializing a documentation set larger than SQLite's variable limit
- **WHEN** search construction needs to inspect more IDs or content hashes than SQLite accepts in one statement
- **THEN** HouDocs queries them in bounded batches
- **AND** indexing continues without a `too many SQL variables` failure

### Requirement: Embedding work is bounded by source document

Search indexing SHALL group search entries by their source document before submitting them to the embedding backend rather than using one version-wide batch. This batching SHALL NOT change entry identity, same-hash embedding reuse, progress totals, or search results.

#### Scenario: Multiple documents require embeddings
- **WHEN** searchable entries from multiple documentation pages require embeddings
- **THEN** each backend upsert contains entries from only one document
- **AND** the progress total represents all unique uncached embeddings required by the staged build
