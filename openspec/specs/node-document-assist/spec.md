# Node Document Assist Specification

## Purpose

HouDocs SHALL keep AI-assisted resolution of exceptional Node parameter mappings outside the normal public CLI while preserving the existing conservative override workflow.

## Requirements

### Requirement: Assist remains an optional maintenance tool

AI-assisted Node parameter resolution SHALL live under `tools/` and SHALL NOT add a public `houdocs` subcommand. Normal `houdocs init`, `search`, `read`, `node`, `hom`, and `vex` behavior SHALL NOT require the assist tool or its prompt.

#### Scenario: Normal HouDocs use

- GIVEN a version has been initialized
- WHEN a user searches or reads documentation
- THEN no AI assist process is invoked
- AND no assist state is required

### Requirement: Assist inputs are derived from initialized version state

`tools/node_document_assist.py` SHALL resolve the effective initialized Houdini version using HouDocs configuration unless `--version` explicitly selects another initialized version. It SHALL read `node-document-unresolved-<version>.json` and `houdini-node-types-<version>.json` from that version's `reports/` directory without accepting arbitrary input file path options.

#### Scenario: Current project selects a version

- GIVEN `.houdocs.toml` selects an initialized Houdini version
- WHEN `node_document_assist.py next` runs without `--version`
- THEN the tool reads that version's unresolved file and runtime NodeType dump

### Requirement: Assist resolution is runtime-grounded

`resolve` SHALL accept only parameter IDs present in the selected NodeType's runtime dump. A successful resolution SHALL be persisted under `overrides.parameters` in the unresolved JSON. A later full `houdocs init` SHALL consume it through the specialized-index override path, while `houdocs init --import-assist` SHALL consume it through its direct database import path.

#### Scenario: AI proposes an existing runtime ID

- GIVEN one unresolved document parameter
- AND the proposed parameter ID exists in the runtime dump for that Node
- WHEN `resolve` is executed
- THEN the version-specific override is written atomically

#### Scenario: AI proposes an invented runtime ID

- GIVEN the proposed parameter ID does not exist in the runtime dump
- WHEN `resolve` is executed
- THEN the tool refuses the resolution
- AND no override is written

### Requirement: Uncertain work can be skipped without mutating the unresolved source

`skip` SHALL record assist-run state separately and SHALL NOT directly modify unresolved mappings. `next` SHALL exclude resolved, skipped, and lifecycle-classified entries and continue until no eligible unresolved Node remains.

#### Scenario: Mapping cannot be proven

- WHEN the resolver skips that document parameter
- THEN its key is persisted in `node-document-assist-state-<version>.json`
- AND the unresolved JSON remains unchanged
- AND subsequent `next` calls continue with other eligible work

### Requirement: Lifecycle classification remains separate from guessed mappings

Unresolved parameters whose Node is absent from the runtime dump MAY be classified into the version-specific lifecycle sidecar. Candidate obsolete/replaced classifications SHALL remain review candidates unless the existing lifecycle logic marks them reviewed.

#### Scenario: Runtime Node is absent

- WHEN lifecycle classification processes an unresolved parameter for a Node absent from the selected runtime dump
- THEN the record is isolated in `node-document-assist-lifecycle-<version>.json`
- AND it is not converted into a fabricated parameter mapping

### Requirement: The AI prompt uses HouDocs interfaces only

The shipped assist prompt SHALL use `node_document_assist.py` for `next`, `resolve`, and `skip`, and MAY use `houdocs node <node>` for additional documentation context. It SHALL NOT require Houbridge commands or direct editing of unresolved JSON.

#### Scenario: JSON context is insufficient

- WHEN the AI cannot resolve a parameter from the `next` payload alone
- THEN it may inspect the corresponding Node with `houdocs node <node>`
- AND if the mapping is still not unique it shall skip rather than guess

### Requirement: Resolved assist overrides can be imported into the existing database

A successful assist `resolve` SHALL remain persisted under `overrides.parameters` in `node-document-unresolved-<version>.json`. `houdocs init --import-assist` SHALL consume only those saved overrides and the existing documentation database; it SHALL not read cached documentation or the saved runtime NodeType dump, or run a fresh Houdini runtime probe.

#### Scenario: Apply completed assist work
- GIVEN an initialized version with saved parameter overrides
- WHEN `houdocs init --import-assist` runs
- THEN manually resolved parameter mappings are applied to the existing Node metadata
- AND no cached documentation or saved runtime NodeType dump is read
- AND the command reports the number actually resolved
