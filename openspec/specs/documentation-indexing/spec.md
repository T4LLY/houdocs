# Documentation Indexing Specification

## Purpose

Define the Help-source acquisition, Bookish parsing, and rebuildable `documents` / `sections` store created during `houdocs init`.

## Requirements

### Requirement: Read loose and archived Houdini Help text

Initialization SHALL recursively read `.txt` files from each runtime-reported Help directory and `.txt` members from `.zip` files. Earlier Help roots SHALL take precedence over later roots for duplicate relative document paths. Loose `.txt` files within a root SHALL take precedence over archive members that resolve to the same relative path.

#### Scenario: Duplicate archive document across Help roots
- **WHEN** two Help roots contain the same archive-relative document path
- **THEN** the document from the earlier runtime-reported Help root is indexed

#### Scenario: Read a Help archive
- **WHEN** `vex.zip` contains `functions/noise.txt`
- **THEN** the cached relative document path is `vex/functions/noise.txt`

### Requirement: Cache Help text as rebuildable version data

Successfully read Help documents SHALL be cached below the selected version's `docs/` directory. The original Houdini Help directories remain authoritative and the cache SHALL NOT be treated as canonical input.

#### Scenario: Cache one archive member
- **WHEN** an archive member is read successfully
- **THEN** its bytes are written below the version `docs/` cache using its resolved relative document path

### Requirement: Parse Bookish documents into shared sections

Initialization SHALL parse cached Bookish text into `documents` and ordered `sections`. The shared `sections.text` store SHALL hold document body content used by later generic and specialist readers.

#### Scenario: Parse heading hierarchy
- **WHEN** a Bookish page contains nested headings and anchors
- **THEN** sections preserve their ordinal, anchor, heading level, heading path semantics, and normalized text

### Requirement: Keep docs indexing incremental

Initialization SHALL compare each document's content hash with the existing version database. Unchanged indexed documents SHALL be skipped, changed documents SHALL replace their sections, and documents absent from the current authoritative Help scan SHALL be removed.

#### Scenario: Reinitialize unchanged Help
- **WHEN** a previously indexed document has the same content hash
- **THEN** that document is counted as skipped

#### Scenario: Remove a deleted Help document
- **WHEN** a previously indexed document no longer appears in the current Help scan
- **THEN** its document row and dependent sections are deleted

### Requirement: Continue after per-document acquisition or parse failures

A failure to read one Help file, read one archive member, open one invalid archive, or parse one Bookish document SHALL be recorded as an initialization error issue and SHALL NOT stop other documents from being indexed. A changed document that cannot be parsed SHALL NOT leave its older indexed body active.

#### Scenario: Invalid archive beside valid Help
- **WHEN** one Help archive is invalid and another document is readable
- **THEN** initialization records a `docs_archive_invalid` error issue
- **AND** continues indexing the readable document

#### Scenario: Changed document cannot be parsed
- **WHEN** a previously indexed document changes and the new content cannot be parsed
- **THEN** initialization records a `bookish_parse_error` error issue
- **AND** removes the older indexed document body

### Requirement: Report document indexing counts

The initialization report SHALL include document counts for total successfully acquired documents, indexed documents, skipped unchanged documents, removed stale documents, and documents that failed during parsing.

#### Scenario: Reinitialize one unchanged document
- **WHEN** one successfully acquired document is already current
- **THEN** the report records `total = 1`, `indexed = 0`, `skipped = 1`, and `failed = 0`
