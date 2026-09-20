# HouDocs

HouDocs is an offline-first CLI for indexing, searching, and reading local SideFX Houdini documentation. It provides structured access to node documentation, HOM Python APIs, VEX functions, general Houdini documentation, and searchable HIP dumps.

After documentation has been initialized for a Houdini version, normal documentation search and read commands use local versioned indexes and do not require a running Houdini process.

## Requirements

- Python 3.11 or later
- A local SideFX Houdini installation for `houdocs init` and `houdocs hip dump`
- [uv](https://docs.astral.sh/uv/)

## Installation

Clone the repository and install its `houdocs` command with uv:

```bash
git clone https://github.com/T4LLY/houdocs.git
cd houdocs
uv tool install .
```

Verify the installation:

```bash
houdocs --help
```

For development without installing the command globally, use `uv sync` and prefix commands with `uv run` instead:

```bash
uv sync
uv run houdocs --help
```

### Install AI skills

After the repository is available at `T4LLY/houdocs`, install its bundled Houdini documentation skill with:

```bash
npx skills add T4LLY/houdocs
```

This installs the `houdini-cli-documents-search` skill for supported AI coding tools.

## Usage

### Initialize documentation

Build the local documentation indexes from an installed Houdini version:

```bash
houdocs init
```

Select a specific installed version when needed:

```bash
houdocs init --houdini-version 22.0.429
```

If no version is selected explicitly or through configuration, HouDocs uses the newest discovered Houdini installation. Initialization collects the installed Help documentation and runtime node metadata, then builds version-local documentation and search databases.

Use `--progress` to show interactive initialization progress on a TTY:

```bash
houdocs init --progress
```

Reinitializing an existing version requires confirmation before its generated databases are rebuilt.

### Search documentation

Search all indexed documentation domains:

```bash
houdocs search "packed primitive"
```

Restrict the search to one domain when the target is already known:

```bash
houdocs search "connect node input" --domain hom
```

Available domains are:

- `node` — Houdini node documentation
- `hom` — HOM Python APIs
- `vex` — VEX functions
- `document` — general Houdini documentation

Search combines lexical and semantic ranking. Results are intentionally compact and contain navigation metadata such as `path`, `kind`, `score`, and `tokens`; use the corresponding reader command to retrieve the actual documentation.

### Read general documentation

Read a complete documentation page:

```bash
houdocs read Node
```

List its sections without loading their bodies:

```bash
houdocs sections Node
```

Read one section directly:

```bash
houdocs read Node setInput
```

When a page title is ambiguous, HouDocs returns numbered candidates. Re-run `read` or `sections` with `--pick N` to select one.

### Read node documentation

Read structured documentation for a node type:

```bash
houdocs node Sop/attribwrangle
```

Node results expose structured inputs, outputs, parameters, and related documentation. A detail path can retrieve one specific item, for example:

```bash
houdocs node Sop/attribwrangle/parameters/snippet
```

### Read HOM documentation

Read one HOM symbol directly:

```bash
houdocs hom hou.Node.setInput
```

### Read VEX documentation

Read one VEX function directly:

```bash
houdocs vex xyzdist
```

### Dump and search HIP files

Create an AI-oriented JSON dump of a HIP file with the matching Houdini `hython` runtime:

```bash
houdocs hip dump --file path/to/scene.hip
```

The dump contains `raw.json` plus searchable network shards under `search/`. Use `--output` to choose a new dump directory or `--houdini-version` to select the Houdini build explicitly.

Search the generated JSON shards without starting Houdini:

```bash
houdocs hip search "camera" --root path/to/dump/search --output hits.json
```

HIP search is an index-free literal search over decoded scalar node fields. The detailed hits are written to the requested JSON file while stdout stays compact.

### Configuration

HouDocs stores global configuration in the platform-standard `houdocs` configuration directory. A `.houdocs.toml` file in the current working directory can override global settings for that directory without being created automatically.

For example, select the default Houdini reference version with:

```toml
[houdini]
version = "22.0.429"
```

An explicit `--houdini-version` passed to `init` or `hip dump` takes precedence over configured versions.

### Common commands

```bash
# Search across all documentation domains.
houdocs search "packed primitive"

# Read structured node documentation.
houdocs node Sop/attribwrangle

# Read a HOM symbol.
houdocs hom hou.Node.setInput

# Read a VEX function.
houdocs vex xyzdist

# List sections of a general documentation page.
houdocs sections Node
```

Run `--help` at any command level to see its available options:

```bash
houdocs hip dump --help
```

## Related tools

`houbridge`, `houdocs`, and `houlayout` are separate CLIs designed for agent orchestration. Each can be assigned only to agents that need its capabilities, keeping command surfaces small and avoiding unnecessary runtime access.

### Houbridge

`houbridge` provides the general Houdini runtime interface: session management, execution, capture, resources, and scene access.

Use it when an agent needs to control a live Houdini session or execute Houdini Python.

### HouDocs

`houdocs` provides structured search and retrieval over locally indexed Houdini documentation.

It can be assigned to agents that need Houdini API and documentation access without exposing general runtime execution. Its HIP tools are separate one-shot dump and offline-search workflows rather than a live session interface.

### Houlayout

`houlayout` is a node-oriented wrapper around Houbridge for inspecting and organizing Houdini networks.

It intentionally exposes a smaller node/layout-focused interface than the general Houbridge runtime surface.

In short:

- `houbridge` — general Houdini runtime and execution
- `houdocs` — structured Houdini documentation search and HIP inspection
- `houlayout` — constrained node and network operations

## License

[MIT License](LICENSE)