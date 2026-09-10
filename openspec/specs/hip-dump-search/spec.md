# HIP Dump and Search Specification

## Purpose

Define one-shot Houdini HIP dumping into AI-oriented JSON shards and index-free offline keyword search over those shards without sending large HIP-derived JSON through stdout.

## Requirements

### Requirement: Expose HIP dump and search as one command group

HouDocs SHALL expose `houdocs hip dump` and `houdocs hip search` under the top-level `hip` command. HIP search SHALL remain independent from the indexed documentation search command and SHALL NOT reuse its search database or backend.

#### Scenario: Inspect HIP commands
- **WHEN** the caller requests `houdocs hip --help`
- **THEN** `dump` and `search` are exposed

### Requirement: Dump one HIP with the selected Houdini version

The public dump command SHALL be `houdocs hip dump --file <HIP_FILE> [--output <DUMP_DIRECTORY>] [--houdini-version <VERSION>] [--timeout <SECONDS>]`. Houdini version resolution SHALL use the same explicit-option-over-configuration precedence as `houdocs init`. `--timeout` SHALL control the headless dump subprocess timeout in seconds, SHALL default to 120 seconds, and SHALL reject non-positive or non-finite values.

#### Scenario: Select a Houdini build explicitly
- **WHEN** the caller runs `houdocs hip dump --file scene.hip --houdini-version 22.0.429`
- **THEN** HouDocs uses the installed Houdini `22.0.429` hython runtime

### Requirement: Create a new dump directory

When `--output` is omitted, HouDocs SHALL create a persistent unique directory under the OS temporary directory. When `--output` is supplied, that path SHALL be treated as the dump directory itself and SHALL be created only when it does not already exist. HouDocs SHALL fail with `hip_dump_output_exists` rather than merging with or replacing an existing output directory.

#### Scenario: Dump without an explicit output
- **WHEN** the caller omits `--output`
- **THEN** HouDocs creates a unique persistent temporary dump directory

#### Scenario: Explicit output already exists
- **WHEN** the caller supplies an existing path with `--output`
- **THEN** dumping fails with `hip_dump_output_exists`
- **AND** Houdini is not started

### Requirement: Write raw and searchable representations separately

A successful dump SHALL contain `raw.json` at the dump root and searchable network JSON shards below `search/`. `raw.json` is an AI-useful native node-network representation of the selected network roots and is not a complete serialization of the HIP file. Searchable shards SHALL be generated for `/obj`, `/stage`, `/mat`, `/out`, and `/tasks` when those roots exist.

#### Scenario: Dump a HIP containing OBJ nodes
- **WHEN** `/obj` exists in the loaded HIP
- **THEN** native node data is represented under `raw.json`
- **AND** the searchable `/obj` network is written below `search/`

### Requirement: Preserve parameter values regardless of size

HIP dump SHALL NOT omit, replace, truncate, or redirect a parameter value merely because it is large. Searchable JSON MAY remove schema/UI-only parameter metadata, but the actual retained parameter value SHALL remain present regardless of its token count.

#### Scenario: Dump a large code parameter
- **WHEN** a parameter contains a large VEX or Python string
- **THEN** the searchable shard contains that string rather than an omission marker or raw reference

### Requirement: Shard editable child networks by reference

Each searchable JSON file SHALL represent one Houdini network. Editable child networks with children SHALL be written to their own shard, and the parent node SHALL contain a `file` reference to that shard. Every `file` reference SHALL be relative to the dump's `search/` root, not relative to the parent shard.

#### Scenario: Dump an editable subnet
- **WHEN** `/obj/geo1` is represented by `search/obj/geo1.json`
- **THEN** its parent node refers to `obj/geo1.json`

### Requirement: Report degraded capture without failing the dump

When native capture falls back to a reduced representation, the dump SHALL remain successful. `raw.json` SHALL contain a top-level `errors` object with `fallback_roots` and `degraded_nodes` arrays describing the degraded captures. Normal stdout SHALL report only the total number of those entries in addition to the dump path.

#### Scenario: One root and two nodes use fallback capture
- **WHEN** one root and two nodes require degraded capture
- **THEN** `raw.json.errors` preserves those three diagnostics
- **AND** stdout contains `"errors":3`

### Requirement: Keep dump stdout minimal

A successful dump SHALL write only the resolved dump directory and degraded-capture error count to stdout as compact JSON.

#### Scenario: Dump succeeds without degraded capture
- **WHEN** HIP dumping completes successfully without fallback capture
- **THEN** stdout is equivalent to `{"output":"/path/to/dump","errors":0}`
- **AND** stdout contains no raw data, shard contents, worker status, or node data

### Requirement: Parse searchable JSON before matching values

The public search command SHALL be `houdocs hip search <QUERY> --root <SEARCH_ROOT> --output <OUTPUT_JSON>`. HouDocs SHALL recursively enumerate and JSON-parse every JSON file below `--root`, then perform literal matching against decoded scalar node-field values. It SHALL NOT use serialized JSON bytes as a prefilter, so JSON escaping SHALL NOT change whether a decoded field matches the query. HouDocs SHALL create no search index and no search database. A query containing only whitespace SHALL fail with `hip_search_query_empty`.

#### Scenario: Query contains a decoded newline
- **WHEN** a field contains a newline represented as an escape sequence in the JSON file
- **AND** the query contains that decoded newline
- **THEN** the field can match after JSON parsing

### Requirement: Resolve hits to node fields

After parsing a shard, HouDocs SHALL resolve matches within scalar node fields. A hit SHALL contain the Houdini node path, search-root-relative file path, RFC 6901 JSON Pointer for the matched scalar field, occurrence count, and reference token count for the full matched field. The token count SHALL use HouDocs' OpenAI `o200k_base` counter.

#### Scenario: Query occurs repeatedly in one field
- **WHEN** one parameter field contains the query three times
- **THEN** one hit is emitted for that node and JSON Pointer
- **AND** `occurrences` is `3`
- **AND** `tokens` describes the complete matched field

### Requirement: Aggregate by node and field

Multiple occurrences within the same scalar field SHALL produce one hit. Distinct fields on the same node SHALL remain distinct hits.

#### Scenario: Two parameters match
- **WHEN** two different parameter fields on one node contain the query
- **THEN** two hits are written with different JSON Pointers

### Requirement: Keep search output outside the search root

`--output` SHALL resolve outside `--root`. HouDocs SHALL fail with `hip_search_output_inside_root` before searching when the output file would be inside the recursive search tree.

#### Scenario: Output is below search root
- **WHEN** `--output` resolves below `--root`
- **THEN** the command fails with `hip_search_output_inside_root`
- **AND** no result file is written

### Requirement: Write hits to the output file and only a summary to stdout

The search output file SHALL contain an object with a `hits` array. Each hit SHALL contain `node`, `file`, `pointer`, `occurrences`, and `tokens`. Normal stdout SHALL contain only the hit count and resolved output path.

#### Scenario: Search finds fourteen fields
- **WHEN** fourteen aggregated hits are written to the output file
- **THEN** stdout is equivalent to `{"hits":14,"output":"/path/to/hits.json"}`
- **AND** stdout contains no hit bodies or node data

### Requirement: HIP search is offline

`houdocs hip search` SHALL depend only on the JSON files below `--root` and the normal HouDocs Python environment. It SHALL NOT start Houdini, import `hou`, open a Houdini command port, or access documentation search databases.

#### Scenario: Houdini is not running
- **WHEN** searchable HIP shards already exist
- **THEN** HIP search can complete without a Houdini process
