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

### Requirement: Rebuild documentation state from fresh staging artifacts

A normal `houdocs init` SHALL construct the selected version's documentation database and Help cache from fresh staging artifacts using the current authoritative Help source. Existing generated `docs.db` contents and the previous `docs/` cache SHALL NOT be used as incremental indexing input. Only a successfully completed staged build SHALL replace the previous generated version artifacts.

#### Scenario: Reinitialize unchanged Help
- **WHEN** a version is initialized again with unchanged authoritative Help
- **THEN** each successfully acquired document is parsed and indexed into the fresh staged database
- **AND** no previous document hash is consulted to skip indexing

#### Scenario: Help document was removed since the previous init
- **WHEN** a document present in the previous generated version state is absent from the current authoritative Help source
- **THEN** the newly built staged documentation state does not contain that document

### Requirement: Continue after per-document acquisition or parse failures

A failure to read one Help file, read one archive member, open one invalid archive, or parse one Bookish document SHALL be recorded as an initialization error issue and SHALL NOT stop other documents from being indexed. A document that cannot be parsed SHALL NOT write a document row or sections into the fresh staged database.

#### Scenario: Invalid archive beside valid Help
- **WHEN** one Help archive is invalid and another document is readable
- **THEN** initialization records a `docs_archive_invalid` error issue
- **AND** continues indexing the readable document

#### Scenario: Document cannot be parsed
- **WHEN** one acquired document cannot be parsed
- **THEN** initialization records a `bookish_parse_error` error issue
- **AND** that document has no active document row or sections in the staged database

### Requirement: Report document indexing counts

The initialization report SHALL include document counts for total successfully acquired documents, successfully indexed documents, and documents that failed during parsing. Incremental-only skipped and removed counts SHALL NOT be reported.

#### Scenario: Index one readable document
- **WHEN** one document is acquired and parsed successfully
- **THEN** the report records `total = 1`, `indexed = 1`, and `failed = 0`
