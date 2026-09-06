# Initialization Progress Specification

## Purpose

Provide optional interactive progress for the long-running `houdocs init` workflow without changing machine-readable command output.

## Requirements

### Requirement: Progress is opt-in and TTY-only

`houdocs init` SHALL expose `--progress`. When enabled on an interactive TTY, initialization progress SHALL be written to stderr using a single updating line. Normal final JSON SHALL remain on stdout. When stderr is not a TTY, progress output SHALL remain silent.

#### Scenario: Interactive initialization
- **WHEN** the caller runs `houdocs init --progress` with stderr attached to a TTY
- **THEN** progress is shown on stderr
- **AND** the final initialization result remains JSON on stdout

#### Scenario: Redirected initialization
- **WHEN** the caller runs `houdocs init --progress` with stderr redirected to a non-TTY stream
- **THEN** no interactive progress text is emitted to that stream

### Requirement: Initialization stages remain visible

Interactive progress SHALL identify the major long-running initialization stages, including Houdini discovery/runtime inspection, Help acquisition/indexing, specialist indexes, and search-index construction.

#### Scenario: Houdini has launched and runtime inspection is still running
- **WHEN** initialization is waiting for the runtime probe to complete
- **THEN** the current progress line identifies Houdini startup/runtime inspection rather than leaving the terminal without status

### Requirement: Document ETA uses the most recent thirty completions

During Help document indexing, ETA SHALL be calculated from the arithmetic mean processing duration of at most the most recent 30 completed documents. Earlier completed documents outside that moving window SHALL NOT influence the ETA. Before 30 documents have completed, all available completed-document samples SHALL be used.

#### Scenario: More than thirty documents have completed
- **WHEN** document 31 completes
- **THEN** the ETA uses completion durations for documents 2 through 31
- **AND** the duration for document 1 no longer contributes

#### Scenario: Fewer than thirty documents have completed
- **WHEN** only 12 documents have completed
- **THEN** the ETA uses those 12 available completion durations

### Requirement: Search embedding work reports uncached counts and recent ETA

When progress is enabled, search-index construction SHALL report the completed and total uncached section embeddings, percentage, and ETA. ETA SHALL use at most the most recent 30 completed embedding batches, weighted by the number of sections completed in those batches. Earlier batches outside that window SHALL NOT influence the estimate. Before the first completed embedding batch, ETA SHALL be unknown. If no embeddings require computation, the progress line SHALL report that embeddings are cached.

#### Scenario: Embedding batches have completed
- **WHEN** at least one uncached embedding batch has completed
- **THEN** progress reports completed/total sections, percentage, and ETA
- **AND** ETA is derived only from the most recent 30 embedding batches

#### Scenario: All embeddings are cached
- **WHEN** search indexing finds zero missing embedding vectors
- **THEN** progress reports `embeddings cached`
