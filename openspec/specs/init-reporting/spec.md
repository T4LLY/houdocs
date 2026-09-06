# Initialization Reporting Specification

## Purpose

Define cumulative machine-readable reporting for non-fatal problems encountered while building a HouDocs version index.

## Requirements

### Requirement: Accumulate non-fatal initialization issues

Initialization SHALL collect non-fatal issues rather than aborting the entire run for the first per-item failure. Issues SHALL identify their severity, kind, and detail and MAY identify a document, symbol, or line when available.

#### Scenario: One runtime node cannot expose parameters
- **WHEN** one node type raises an error during parameter introspection
- **THEN** initialization records a `warning` issue for that node
- **AND** continues processing other node types

### Requirement: Distinguish warnings from errors

An item that was read but could not be completely resolved SHALL be reported as a warning. An item that cannot be parsed or indexed SHALL be reported as an error. Fatal prerequisites such as failure to launch Houdini or failure to obtain Help roots MAY terminate initialization immediately through the normal HouDocs error contract.

#### Scenario: Runtime metadata is incomplete
- **WHEN** a node exists but its parameter introspection fails
- **THEN** the issue severity is `warning`

### Requirement: Persist the complete report per Houdini version

Initialization SHALL write the complete report to `<version-root>/reports/init-report.json` and SHALL return the same report payload to the CLI caller.

#### Scenario: Initialization completes with warnings
- **WHEN** initialization completes and warnings were collected
- **THEN** `init-report.json` contains every collected warning
- **AND** the command result includes warning and error counts

### Requirement: Preserve the runtime node dump for maintenance tools

Initialization SHALL persist the runtime node snapshot as `houdini-node-types-<version>.json` under the version report directory so optional unresolved-node maintenance tooling can reuse the same runtime evidence without opening another Houdini session.

#### Scenario: Runtime capture completes
- **WHEN** initialization captures node types for Houdini `22.0.429`
- **THEN** `reports/houdini-node-types-22.0.429.json` is written
