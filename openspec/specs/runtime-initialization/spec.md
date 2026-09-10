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

### Requirement: Keep Houdini execution targeting internal

Initialization SHALL create its Houdini runtime session internally and SHALL NOT require public host, port, hcommand, or executable selection options.

#### Scenario: Initialize an installed version
- **WHEN** the caller runs `houdocs init --houdini-version 22.0.429`
- **THEN** HouDocs starts the selected Houdini installation and creates its local runtime session internally
- **AND** the caller supplies no host, port, hcommand, or executable path

### Requirement: Obtain Help directories from Houdini

Initialization SHALL ask the selected Houdini runtime for `hou.findDirectories("help")` and SHALL use the accessible returned directories as the documentation source roots.

#### Scenario: Runtime reports Help roots
- **WHEN** Houdini reports one or more accessible Help directories
- **THEN** initialization records those directories for the selected runtime version

#### Scenario: Runtime reports no accessible Help root
- **WHEN** no reported Help directory is accessible
- **THEN** initialization fails with `docs_source_missing`

### Requirement: Capture runtime node parameter metadata once during init

Initialization SHALL collect runtime node types and their parameter templates, including parameter IDs, labels, folder paths, type information, component counts, multiparm information, and ordering metadata. It SHALL also capture each node type's minimum/maximum input counts and maximum output count. Importing HouDocs or using normal reader commands SHALL NOT import `hou`.

#### Scenario: Capture node parameters
- **WHEN** a runtime node type has parameters
- **THEN** initialization captures those parameter records as the canonical Node parameter structure and for later documentation reverse resolution

#### Scenario: Capture node port structure
- **WHEN** a runtime node type reports input/output limits
- **THEN** initialization captures those counts so Node reads do not depend on an `@inputs` or `@outputs` documentation section to expose ports

#### Scenario: Parameter introspection fails for one node
- **WHEN** parameter collection fails for one runtime node type
- **THEN** initialization continues collecting other node types
- **AND** records that node failure as an initialization warning


### Requirement: Validate runtime metadata at the runtime boundary

The Houdini probe payload SHALL be validated and converted to typed runtime node and parameter records before specialized indexers consume it. Specialized indexers SHALL NOT interpret raw probe dictionaries. The original probe payload MAY still be persisted unchanged as runtime evidence. Malformed nested node or parameter metadata SHALL fail initialization with `runtime_probe_invalid`.

#### Scenario: Runtime returns malformed parameter metadata
- **WHEN** a runtime parameter record has an invalid field shape
- **THEN** initialization fails with `runtime_probe_invalid` before Node indexing begins
- **AND** the Node indexer does not receive the malformed raw record

### Requirement: Verify the actual runtime version

The runtime-reported Houdini version SHALL be checked against an explicitly or configurationally requested version before version-specific derived state is written.

#### Scenario: Runtime version mismatches an exact request
- **WHEN** `22.0.429` is requested
- **AND** the runtime reports `22.0.430`
- **THEN** initialization fails with `houdini_version_mismatch`

### Requirement: Use a reusable local Houdini session boundary

HouDocs SHALL encapsulate temporary Houdini process launch, local command-port discovery, `hcommand` execution, temporary session files, and process termination in a reusable Houdini session component. Init-specific probe code SHALL consume that session instead of managing ports or processes itself. The session SHALL let Houdini choose a free local command port and SHALL NOT reserve a port in a separate process before launch. HIP dumping MAY use the selected installation's `hython` directly for its independent one-shot worker and SHALL NOT change the init session lifecycle.

#### Scenario: Run the initialization probe
- **WHEN** initialization needs runtime metadata
- **THEN** HouDocs creates a local Houdini session for the selected installation
- **AND** executes the init probe through that session's command port
- **AND** the probe owns only its worker/result contract, not Houdini process or port management

#### Scenario: Run HIP dumping
- **WHEN** HIP dumping needs to load and inspect a HIP
- **THEN** it may execute its self-contained worker with the selected installation's `hython`
- **AND** it shares installation selection and environment construction without replacing the init session model

### Requirement: Launch the selected Houdini tools with a consistent environment

A spawned Houdini or hython process and `hcommand` invocation SHALL set `HFS` to the selected installation root and place that installation's `bin` directory first in `PATH` without duplicating that same directory. Existing environment values from another Houdini installation SHALL NOT override the explicitly selected installation.

#### Scenario: Parent environment points at another Houdini
- **WHEN** HouDocs selects Houdini `22.0.429`
- **AND** the parent environment contains `HFS` or an earlier `PATH` entry for another Houdini build
- **THEN** spawned Houdini tools use the selected `22.0.429` root as `HFS`
- **AND** its `bin` directory is first in `PATH`

### Requirement: Resolve installation version from installation metadata when available

Installation discovery SHALL prefer Houdini's installed version metadata over inferring the version only from the installation directory name. Directory-name parsing MAY be used as a fallback. A candidate whose version cannot be identified SHALL NOT be exposed as an installed version with a synthetic `0.0.0` value.

#### Scenario: Installation uses a custom path name
- **WHEN** a valid Houdini installation is located at a path that does not contain its version
- **AND** its installed version metadata reports `22.0.429`
- **THEN** discovery identifies the installation as `22.0.429`

### Requirement: Serialize init mutations per HouDocs data root

HouDocs SHALL allow at most one init mutation at a time for a HouDocs data root. The exclusion SHALL use an OS-backed non-blocking lock rather than treating lock-file existence or a stored PID as authoritative. The lock policy belongs to init; the underlying lock primitive MAY be reused by other operations with their own policies.

#### Scenario: Another init is already running
- **WHEN** the init lock for the same HouDocs data root is already held
- **THEN** a second init attempt fails immediately with `init_in_progress`
- **AND** it does not select or launch Houdini

#### Scenario: Previous process exited abnormally
- **WHEN** a lock file remains on disk but no process holds the OS lock
- **THEN** a later init can acquire the lock normally
