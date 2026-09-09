# Versioned Storage Specification

## Purpose

Keep all rebuildable HouDocs artifacts isolated by Houdini version.

## Requirements

### Requirement: Use the platform-standard HouDocs data root

HouDocs SHALL use `platformdirs.user_data_path("houdocs")` as the default data root.

#### Scenario: Resolve default storage
- **WHEN** no alternate data root is supplied by an internal test or embedding context
- **THEN** HouDocs derives its persistent data root from the platformdirs `houdocs` namespace

### Requirement: Isolate derived state by Houdini version

Each initialized Houdini version SHALL use its own directory under `<data-root>/versions/<version>/` containing that version's documentation database, search database, extracted/cached documentation, and initialization reports.

#### Scenario: Resolve paths for Houdini 22.0.429
- **WHEN** version paths are requested for `22.0.429`
- **THEN** the version root is `<data-root>/versions/22.0.429/`
- **AND** `docs.db` and `search.db` are located below that root
- **AND** cached documentation and reports are also located below that root

#### Scenario: Two Houdini versions are initialized
- **WHEN** derived state exists for `21.0.547` and `22.0.429`
- **THEN** each version uses a different version root
- **AND** writes for one version cannot replace the other version's databases

### Requirement: Creating a version path does not fabricate initialized databases

Preparing version directories SHALL create only required directories and SHALL NOT create placeholder `docs.db` or `search.db` files before their owning indexing phases write them.

#### Scenario: Prepare a new version tree
- **WHEN** the version path is ensured for a version that has never been initialized
- **THEN** the version root, docs cache directory, and reports directory exist
- **AND** `docs.db` and `search.db` remain absent

### Requirement: Init owns generated database schema lifecycle

Normal `houdocs init` SHALL create the fixed schemas for the fresh staged `docs.db` and `search.db` before repositories or search backends use them. Repository and search-backend construction SHALL NOT create, migrate, or repair generated databases. Normal offline `read`, `sections`, `node`, `hom`, `vex`, and `search` operations SHALL open their generated database state read-only and SHALL NOT change schema, journal mode, or database contents as a side effect of reading.

#### Scenario: Read initialized documentation
- **WHEN** a normal offline command opens an existing initialized database
- **THEN** it uses the existing generated schema without creating or migrating tables
- **AND** the read does not change the database journal mode or stored contents

#### Scenario: Construct a repository for a missing database
- **WHEN** an internal caller constructs a repository or search backend for a path whose generated database does not exist
- **THEN** construction alone does not create a database file or schema

#### Scenario: Build fresh staged databases
- **WHEN** normal initialization starts indexing a fresh staged version state
- **THEN** init explicitly creates the fixed documentation and search schemas before their repositories and backend perform writes
- **AND** profile-specific sqlite-vec tables MAY still be created by the vector-storage component when the embedding dimensions become known
