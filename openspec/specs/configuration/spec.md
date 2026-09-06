# Configuration Specification

## Purpose

Define global HouDocs configuration and current-directory Houdini-version selection.

## Requirements

### Requirement: Use global configuration with optional current-directory overrides

HouDocs SHALL use `config.toml` under `platformdirs.user_config_path("houdocs")` as global configuration. If that file does not exist, HouDocs SHALL create it with supported defaults. If `<current-working-directory>/.houdocs.toml` exists, its tables SHALL recursively override global values. The local file SHALL NOT be auto-created.

#### Scenario: First configuration load
- **WHEN** a command first requires configuration and global `config.toml` does not exist
- **THEN** HouDocs creates the global configuration file
- **AND** the generated configuration leaves the default Houdini version unspecified

#### Scenario: Current directory selects another Houdini version
- **WHEN** global configuration selects Houdini `21.0.547`
- **AND** `.houdocs.toml` selects Houdini `22.0.429`
- **THEN** the effective configured version is `22.0.429`

#### Scenario: No local config exists
- **WHEN** `.houdocs.toml` is absent
- **THEN** HouDocs does not create it
- **AND** global configuration remains effective

### Requirement: Store the default reference version under the Houdini table

The `[houdini].version` setting SHALL hold the optional default reference version. An empty string SHALL mean that configuration does not select a version.

#### Scenario: Version is not configured
- **WHEN** `[houdini].version` is empty
- **THEN** configuration resolves the default version as unspecified

#### Scenario: Version is configured
- **WHEN** `[houdini].version` is `22.0.429`
- **THEN** commands resolving a configured reference version receive `22.0.429`

### Requirement: Explicit init version has highest precedence

When `houdocs init` receives `--houdini-version`, that value SHALL override both current-directory and global configured versions for that invocation.

#### Scenario: CLI version overrides local configuration
- **WHEN** `.houdocs.toml` selects `21.0.547`
- **AND** the caller runs init with `--houdini-version 22.0.429`
- **THEN** the requested initialization version is `22.0.429`

### Requirement: Reject path-like or malformed version values

Configured or explicitly supplied Houdini versions SHALL use numeric `major.minor` or `major.minor.build` form and SHALL NOT be interpreted as filesystem paths.

#### Scenario: Malformed local version is loaded
- **WHEN** `.houdocs.toml` contains `version = "../22.0.429"`
- **THEN** configuration fails with `invalid_config`
