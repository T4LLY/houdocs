# Offline Reader Specification

## Purpose

Define the normal `read`, `node`, `python`, and `vex` commands after initialization.

## Requirements

### Requirement: Normal readers are offline

`houdocs read`, `houdocs node`, `houdocs python`, and `houdocs vex` SHALL read only version-local derived state after init and SHALL NOT import `hou`, open a Houdini session, or require host/port information.

#### Scenario: Houdini is not running
- **WHEN** a selected version has already been initialized
- **AND** no Houdini process is running
- **THEN** all four reader commands can resolve indexed documentation

### Requirement: Read accepts only page and optional section

The public command SHALL be `houdocs read <page> [section]`. A page name SHALL resolve by indexed document title. An optional section SHALL match indexed anchor, heading, or heading path using the existing document-reader matching semantics.

#### Scenario: Read a complete page
- **WHEN** the caller provides only a page title
- **THEN** HouDocs returns the document metadata, `section: null`, and the complete indexed page text

#### Scenario: Read a section
- **WHEN** the caller also provides an unambiguous section name
- **THEN** HouDocs returns only that indexed section text and structured section metadata

### Requirement: Specialized commands use direct specialized indexes

`houdocs node <node-type>`, `houdocs python <symbol>`, and `houdocs vex <function>` SHALL first resolve their target through `node_documents`, `python_documents`, or `vex_documents` respectively. They SHALL obtain body text from the common `sections` store rather than duplicating bodies in specialized tables.

#### Scenario: Read a Python method
- **WHEN** `python_documents` contains `hou.Node.setInput`
- **THEN** `houdocs python hou.Node.setInput` directly resolves its document and stored signatures
- **AND** returns the member body extracted from that document's indexed sections

#### Scenario: Read a VEX overload set
- **WHEN** `vex_documents` contains multiple signatures for `xyzdist`
- **THEN** `houdocs vex xyzdist` returns all stored signatures and structured VEX metadata with the common page text

#### Scenario: Read a Node type
- **WHEN** `node_documents` contains `Sop/attribwrangle`
- **THEN** `houdocs node Sop/attribwrangle` returns node metadata, inputs, outputs, documented parameter mappings, related links, and common page text in one response

### Requirement: Resolve the effective initialized Houdini version without reader options

Reader/search commands SHALL use `[houdini].version` from effective configuration when set. A configured `major.minor` SHALL select the newest initialized build in that release. When no version is configured, the newest initialized version SHALL be used. Public reader/search commands SHALL NOT add a version option.

#### Scenario: Current directory selects a release
- **WHEN** `.houdocs.toml` selects `22.0`
- **AND** initialized builds include `22.0.400` and `22.0.429`
- **THEN** the reader uses `22.0.429`

#### Scenario: No index exists
- **WHEN** no initialized version can satisfy the effective version selection
- **THEN** the command fails with `docs_index_missing`
