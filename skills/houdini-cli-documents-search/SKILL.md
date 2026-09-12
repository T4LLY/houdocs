---
name: houdini-cli-documents-search
description: Search and read locally indexed SideFX Houdini documentation, including node parameters and ports, HOM Python APIs, VEX functions, and general Houdini documentation. Use HouDocs progressively to retrieve only the documentation needed for the current task.
---

# Houdini Docs

HouDocs is a CLI tool for researching Houdini documentation.

Use it to look up Houdini nodes, parameters, inputs and outputs, HOM Python APIs, VEX functions, and general documentation.

## Basic Principles

Retrieve only the information needed for the current task.
Do not load large amounts of documentation up front.

Use this general workflow:

1. If the target is already known, use the dedicated reader directly.
2. If the target is unclear, use search to find candidates.
3. Check tokens before reading additional content.
4. Read only the required section, parameter, or port details.

Do not run houdocs init during normal documentation research.

If the index does not exist, report that state instead.

# Search

## When the target is unclear

houdocs search "<query>"

## Restrict the search when the domain is known

- Node information: houdocs search "<query>" --domain node
- Houdini Python: houdocs search "<query>" --domain hom
- VEX: houdocs search "<query>" --domain vex
- General documentation: houdocs search "<query>" --domain document

Search results do not contain the full document body. They mainly return:

- path: Path used to identify the target
- kind: Document type
- score: Relevance score
- tokens: Estimated token count for reading the detailed content

Do not answer from search results alone.
Use the appropriate reader for the returned kind and inspect the relevant content.

- node → houdocs node
- hom → houdocs hom
- vex → houdocs vex
- document → houdocs read

If a general-documentation path is ["PAGE", "SECTION"], read it with:

houdocs read "<PAGE>" "<SECTION>"

# Node

If the node type is already known, read it directly without searching first.

houdocs node Sop/attribwrangle

## Node Overview

A node overview mainly contains:

- inputs
- outputs
- parameters
- related

If jq is available, use it to retrieve only the required field and reduce output size.

houdocs node Sop/attribwrangle | jq ".inputs"

houdocs node Sop/attribwrangle | jq ".outputs"

houdocs node Sop/attribwrangle | jq ".parameters"

houdocs node Sop/attribwrangle | jq ".related"

To retrieve only parameter IDs:

houdocs node Sop/attribwrangle | jq -r ".parameters[].id"

Parameters, inputs, and outputs do not include their full descriptions in the overview.
Instead, they include tokens indicating the estimated size of the corresponding detail.

## Read Only the Required Detail

Parameter:

houdocs node Sop/attribwrangle/parameters/<id>

Input:

houdocs node Sop/example/inputs/0

Output:

houdocs node Sop/example/outputs/0

If a parameter entry has an id, use that ID to read the parameter.

If a parameter has not been resolved to a runtime parameter, use ordinal instead.

Do not assume that reading the node overview also retrieves the detailed descriptions of its parameters, inputs, or outputs.

# HOM

If the HOM symbol is already known:

houdocs hom hou.Node.setInput

If the exact symbol is unknown:

houdocs search "<query>" --domain hom

Identify the symbol from the search results, then read its documentation with houdocs hom.

# VEX

If the VEX function is already known:

houdocs vex xyzdist

If the exact function is unknown:

houdocs search "<query>" --domain vex

Identify the function from the search results, then read its documentation with houdocs vex.

# General Documentation

If the target page is not already known, search first.

houdocs search "<query>" --domain document

Before reading an entire page, inspect its section list.

houdocs sections "<PAGE>"

The section list includes tokens for each section.

Read only the sections required for the current task.

houdocs read "<PAGE>" "<SECTION>"

Read the entire page only when necessary:

houdocs read "<PAGE>"

# Ambiguous Documents

If multiple documents have the same name, HouDocs returns candidate documents.

Inspect the candidates and select the intended one explicitly.

houdocs read "<PAGE>" --pick <N>

The same --pick option can be used when listing sections.

houdocs sections "<PAGE>" --pick <N>

Do not guess when multiple candidates are available.

# Token Discipline

Use tokens as an estimate of the cost of retrieving additional detail.

For general documentation, prefer this progression:

search
→ compact metadata
→ relevant section/detail
→ full page only when necessary

For nodes, prefer:

node overview
→ extract only the required field with jq
→ relevant parameter/input/output detail

Do not read high-token sections or details that are unrelated to the current question.

If multiple sections or details are required for an accurate answer, inspect all of the relevant ones.

# Grounding

When answering questions about Houdini node behavior, parameters, ports, HOM APIs, or VEX functions, verify the actual documentation with HouDocs whenever possible.

Do not infer parameter IDs, port meanings, HOM methods, or VEX signatures from names alone.

Do not determine behavior from only a search result title or path.
Read the relevant documentation body with the appropriate reader.

Do not present information as documented by HouDocs unless it is actually present in the retrieved documentation.