# CLI Interface Specification

## Purpose

Define the minimal public HouDocs command surface without exposing internal indexing or connection mechanics.

## Requirements

### Requirement: Expose six top-level documentation commands

HouDocs SHALL expose exactly the documentation workflow commands `init`, `search`, `read`, `node`, `hom`, and `vex` at the top level in the initial public interface.

#### Scenario: Inspect the top-level CLI
- **WHEN** the caller requests top-level help
- **THEN** `init`, `search`, `read`, `node`, `hom`, and `vex` are exposed
- **AND** no public `rebuild` command is exposed

### Requirement: Search may target one documentation domain

The public search command SHALL accept one query positional argument and an optional `--domain` selector with values `node`, `vex`, `hom`, and `document`. Omitting `--domain` SHALL search all four domains.

#### Scenario: Search all documentation domains
- **WHEN** the caller runs `houdocs search "packed primitive"`
- **THEN** HouDocs searches `node`, `vex`, `hom`, and `document` together

#### Scenario: Search only HOM
- **WHEN** the caller runs `houdocs search "connect node input" --domain hom`
- **THEN** HouDocs searches HOM symbol entries only

### Requirement: Keep generic reads page-oriented

The public read command SHALL accept a page positional argument and an optional section positional argument.

#### Scenario: Read a complete page
- **WHEN** the caller runs `houdocs read Node`
- **THEN** `Node` is treated as the requested page
- **AND** no section filter is applied

#### Scenario: Read one page section
- **WHEN** the caller runs `houdocs read Node setInput`
- **THEN** `Node` is treated as the page
- **AND** `setInput` is treated as the requested section

### Requirement: Keep specialist readers identifier-only

The public `node`, `hom`, and `vex` commands SHALL each accept one specialist identifier and SHALL return their complete structured specialist result rather than exposing output-filter options.

#### Scenario: Request node documentation
- **WHEN** the caller runs `houdocs node Sop/attribwrangle`
- **THEN** the command uses `Sop/attribwrangle` as the complete node-type identifier

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
