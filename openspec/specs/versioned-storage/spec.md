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
