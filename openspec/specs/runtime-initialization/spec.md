# Runtime Initialization Specification

## Purpose

Define the one-time Houdini runtime access used by `houdocs init` to discover the authoritative Help directories and capture runtime node/parameter metadata without making normal HouDocs reads depend on Houdini.

## Requirements

### Requirement: Resolve an installed Houdini from the requested version

`houdocs init` SHALL select an installed Houdini using the effective requested version. A `major.minor.build` request SHALL require that build. A `major.minor` request SHALL select the newest installed build in that release. If no version is requested, the newest discovered installation SHALL be selected.

#### Scenario: Select a full build
- **WHEN** Houdini `22.0.429` is requested and installed
- **THEN** initialization uses the `22.0.429` installation

#### Scenario: Select a release without build
- **WHEN** Houdini `22.0` is requested
- **AND** builds `22.0.400` and `22.0.429` are installed
- **THEN** initialization uses `22.0.429`

#### Scenario: Requested version is unavailable
- **WHEN** Houdini `21.5.999` is requested and not installed
- **THEN** initialization fails with `houdini_version_not_found`

### Requirement: Keep connection targeting internal

Initialization SHALL create its runtime session internally and SHALL NOT require public host, port, hcommand, or executable selection options.

#### Scenario: Initialize an installed version
- **WHEN** the caller runs `houdocs init --houdini-version 22.0.429`
- **THEN** HouDocs starts the selected Houdini installation as needed
- **AND** chooses the local connection port internally
- **AND** the caller supplies no host or port

### Requirement: Obtain Help directories from Houdini

Initialization SHALL ask the selected Houdini runtime for `hou.findDirectories("help")` and SHALL use the accessible returned directories as the documentation source roots.

#### Scenario: Runtime reports Help roots
- **WHEN** Houdini reports one or more accessible Help directories
- **THEN** initialization records those directories for the selected runtime version

#### Scenario: Runtime reports no accessible Help root
- **WHEN** no reported Help directory is accessible
- **THEN** initialization fails with `docs_source_missing`

### Requirement: Capture runtime node parameter metadata once during init

Initialization SHALL collect runtime node types and their parameter templates, including parameter IDs, labels, folder paths, type information, component counts, multiparm information, and ordering metadata. Importing HouDocs or using normal reader commands SHALL NOT import `hou`.

#### Scenario: Capture node parameters
- **WHEN** a runtime node type has parameters
- **THEN** initialization captures those parameter records for later documentation reverse resolution

#### Scenario: Parameter introspection fails for one node
- **WHEN** parameter collection fails for one runtime node type
- **THEN** initialization continues collecting other node types
- **AND** records that node failure as an initialization warning

### Requirement: Verify the actual runtime version

The runtime-reported Houdini version SHALL be checked against an explicitly or configurationally requested version before version-specific derived state is written.

#### Scenario: Runtime version mismatches an exact request
- **WHEN** `22.0.429` is requested
- **AND** the runtime reports `22.0.430`
- **THEN** initialization fails with `houdini_version_mismatch`
