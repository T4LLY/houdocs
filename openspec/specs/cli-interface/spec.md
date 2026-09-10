# CLI Interface Specification

## Purpose

Define the minimal public HouDocs command surface without exposing internal indexing or connection mechanics.

## Requirements

### Requirement: Expose eight top-level commands

HouDocs SHALL expose exactly `init`, `search`, `read`, `sections`, `node`, `hom`, `vex`, and `hip` at the top level in the public interface.

#### Scenario: Inspect the top-level CLI
- **WHEN** the caller requests top-level help
- **THEN** `init`, `search`, `read`, `sections`, `node`, `hom`, `vex`, and `hip` are exposed
- **AND** no public `rebuild` command is exposed


### Requirement: Keep HIP operations grouped under hip

The top-level `hip` command SHALL expose `dump` and `search` subcommands. HIP dump MAY expose `--file`, `--output`, `--houdini-version`, and `--timeout`; HIP search MAY expose `--root` and `--output`. HIP-specific options SHALL NOT be added to the documentation `search` command.

#### Scenario: Inspect HIP command help
- **WHEN** the caller requests `houdocs hip --help`
- **THEN** `dump` and `search` are exposed as subcommands
- **AND** documentation search remains a separate top-level command

### Requirement: Search may target one documentation domain

The public search command SHALL accept one query positional argument and an optional `--domain` selector with values `node`, `vex`, `hom`, and `document`. Omitting `--domain` SHALL search all four domains.

#### Scenario: Search all documentation domains
- **WHEN** the caller runs `houdocs search "packed primitive"`
- **THEN** HouDocs searches `node`, `vex`, `hom`, and `document` together

#### Scenario: Search only HOM
- **WHEN** the caller runs `houdocs search "connect node input" --domain hom`
- **THEN** HouDocs searches HOM symbol entries only

### Requirement: Keep generic reads page-oriented

The public read command SHALL accept a page positional argument, an optional section positional argument, and `--pick N` only for selecting a numbered candidate when a page title is ambiguous.

#### Scenario: Read a complete page
- **WHEN** the caller runs `houdocs read Node`
- **THEN** `Node` is treated as the requested page
- **AND** no section filter is applied

#### Scenario: Read one page section
- **WHEN** the caller runs `houdocs read Node setInput`
- **THEN** `Node` is treated as the page
- **AND** `setInput` is treated as the requested section

#### Scenario: Resolve an ambiguous page title
- **WHEN** a page title matches more than one indexed document
- **THEN** HouDocs returns numbered human-readable candidates
- **AND** the caller can re-run `houdocs read <page> --pick N` to select one candidate
- **AND** the candidate list does not expose an internal document ID or source path

### Requirement: List page sections without reading their bodies

The public `sections` command SHALL accept a page positional argument and `--pick N` only for selecting a numbered candidate when a page title is ambiguous. It SHALL return the ordered section paths and token counts for the selected page without returning section body text.

#### Scenario: List sections for one page
- **WHEN** the caller runs `houdocs sections Node`
- **THEN** HouDocs returns the page's sections in document order
- **AND** each section includes its heading path and token count
- **AND** section body text is not returned

#### Scenario: Resolve an ambiguous page title for section listing
- **WHEN** a page title matches more than one indexed document
- **THEN** HouDocs returns numbered human-readable candidates
- **AND** the caller can re-run `houdocs sections <page> --pick N` to select one candidate
- **AND** the candidate list does not expose an internal document ID or source path

### Requirement: Keep specialist readers identifier-only

The public `node`, `hom`, and `vex` commands SHALL each accept one specialist identifier rather than exposing output-filter options. `node` MAY extend the node identifier with a detail path for one input, output, or parameter.

#### Scenario: Request node documentation
- **WHEN** the caller runs `houdocs node Sop/attribwrangle`
- **THEN** the command uses `Sop/attribwrangle` as the node-type identifier

#### Scenario: Request one node parameter description
- **WHEN** the caller runs `houdocs node Sop/attribwrangle/parameters/snippet`
- **THEN** the command resolves `Sop/attribwrangle` and returns only the description for parameter `snippet`

#### Scenario: Request HOM documentation
- **WHEN** the caller runs `houdocs hom hou.Node.setInput`
- **THEN** the command uses `hou.Node.setInput` as the complete HOM symbol

#### Scenario: Request VEX documentation
- **WHEN** the caller runs `houdocs vex xyzdist`
- **THEN** the command uses `xyzdist` as the complete VEX function identifier

### Requirement: Keep initialization free of public connection-target options

The public init command MAY accept `--houdini-version` but SHALL NOT expose `--host`, `--port`, or `--executable` as user-facing connection selection options.

#### Scenario: Inspect initialization options
- **WHEN** the caller requests `houdocs init --help`
- **THEN** `--houdini-version` is available
- **AND** `--host`, `--port`, and `--executable` are absent

### Requirement: Protect existing initialization state

When the selected Houdini version already has a `docs.db`, `houdocs init` SHALL require an interactive `y/N` confirmation before rebuilding that database. The default answer SHALL be `N`.

#### Scenario: Existing database is not confirmed
- **WHEN** the caller runs `houdocs init` for an already initialized version
- **AND** the caller does not answer `y`
- **THEN** HouDocs stops before rebuilding the existing database

### Requirement: Import saved assist overrides without full initialization

The public init command SHALL expose `--import-assist`. This mode SHALL read the saved unresolved override report and apply its saved Node parameter overrides directly to existing Node metadata in the documentation database without running the normal full initialization workflow. It SHALL not read the cached documentation or saved Node runtime dump, and SHALL not run Node reindexing or resolution. Successful output SHALL be one concise text line reporting the number of overrides actually resolved.

#### Scenario: Import saved assist mappings
- **WHEN** the caller runs `houdocs init --import-assist` for an initialized version
- **THEN** HouDocs reads the saved unresolved override report and the existing `docs.db`
- **AND** updates only the targeted Node metadata in the existing `docs.db`
- **AND** does not read the saved Node runtime dump or documentation cache
- **AND** does not run Node reindexing or resolution
- **AND** does not rebuild the general documentation or search indexes
- **AND** prints `Imported N assist overrides.`
