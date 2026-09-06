# Specialized Documentation Indexing

## Purpose

HouDocs MUST build dedicated Node, Python/HOM, and VEX lookup indexes during `houdocs init` while keeping documentation body text canonical in `sections`.

## Requirements

### Requirement: Specialized indexes are derived during init

`houdocs init` MUST build `node_documents`, `python_documents`, and `vex_documents` in the selected Houdini version's `docs.db` after the common `documents` and `sections` index is available.

#### Scenario: Specialized indexing succeeds

- GIVEN common documentation has been indexed
- WHEN initialization continues
- THEN Node, Python/HOM, and VEX lookup indexes are rebuilt from the current cached Help source
- AND no specialized table duplicates full documentation body text

### Requirement: Node resolution uses runtime introspection conservatively

Node documentation MUST be matched against the runtime NodeType snapshot collected by the same init run. Documented parameter IDs MUST be validated against runtime IDs when runtime information is available. Missing IDs MAY be resolved by a unique runtime label, a unique folder-and-label match, or an unambiguous position between already resolved neighboring parameters.

#### Scenario: Unique runtime parameter match

- GIVEN a documented parameter has no explicit ID
- AND exactly one runtime parameter has the matching label
- WHEN the Node index is built
- THEN the documented parameter is linked to that runtime parameter
- AND its resolution source identifies Houdini runtime resolution

#### Scenario: Parameter remains ambiguous

- GIVEN a documented parameter cannot be mapped uniquely to a runtime parameter
- WHEN the Node index is built
- THEN no guessed runtime ID is created
- AND the parameter remains unresolved
- AND initialization continues

### Requirement: Node unresolved data is persistent and override-aware

Each version MUST maintain `node-document-unresolved-<version>.json` beside the version's init reports. Existing `overrides.parameters` and `overrides.related` entries MUST be preserved and applied on later init runs before unresolved output is rewritten.

#### Scenario: Manual override is reused

- GIVEN an unresolved file contains a valid parameter override for the selected version
- WHEN `houdocs init` runs again
- THEN the override is validated against the current runtime parameter set
- AND the mapping is recorded with manual resolution provenance
- AND the override remains in the rewritten unresolved file

### Requirement: Every unresolved Node item is reported

Unresolved Node types, parameters, and related links MUST be retained in the unresolved JSON and MUST also be emitted as warning issues in the aggregate init report.

#### Scenario: One parameter cannot be resolved

- WHEN Node indexing encounters that parameter
- THEN initialization does not fail solely because of that unresolved item
- AND `init-report.json` contains a warning for it
- AND the unresolved JSON contains its document, ordinal, and reason

### Requirement: Python/HOM symbols are directly indexed

Pages with Bookish `#type: homclass`, `hommodule`, or `homfunction` MUST create direct symbol lookup rows. Class and module members MUST create their own symbol rows, and all discovered overload signatures for a symbol MUST be retained.

#### Scenario: Class method is indexed

- GIVEN `hou.Node` documents `setInput` overloads
- WHEN init builds the Python index
- THEN `python_documents` contains `hou.Node.setInput`
- AND the row identifies `hou.Node` as its parent
- AND every discovered `setInput` signature is stored
- AND the row does not duplicate the method body text

### Requirement: VEX functions preserve structured metadata

Pages with Bookish `#type: vex` MUST create a direct function lookup row containing all discovered signatures plus `#context`, `#group`, `#tags`, and `#status` metadata when present.

#### Scenario: VEX overloads are indexed

- GIVEN a VEX function page contains multiple signatures
- WHEN init builds the VEX index
- THEN every signature is retained in `vex_documents`
- AND contexts, group, tags, and status are stored separately
- AND the row does not duplicate the function body text

### Requirement: Specialized parse failures are aggregated

A failure to parse one specialized document MUST be recorded as an init error issue for that document and MUST NOT stop unrelated specialized documents from being indexed.

#### Scenario: One specialized page is malformed

- WHEN its specialized parser raises an error
- THEN the item contributes to that specialized index's failed count
- AND an error issue is added to `init-report.json`
- AND indexing continues with remaining documents
