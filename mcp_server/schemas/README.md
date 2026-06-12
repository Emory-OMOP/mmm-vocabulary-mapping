# OMOP CDM Schema Files

These schema files were extracted from the [fastomop/omcp](https://github.com/fastomop/omcp)
repository (`feat/niko-a2a` branch, commit `cc9ee0f`) and are used here as static MCP
resources to provide LLM clients with OMOP CDM table structure context.

## Source

- **Repository**: https://github.com/fastomop/omcp
- **Branch**: `feat/niko-a2a`
- **Commit**: `cc9ee0fe0084199e7577a653c16caf4a998fdc9f`
- **License**: MIT (Copyright (c) 2025 fastomop)
- **Date extracted**: 2026-02-17

## Files

| File | Description |
|------|-------------|
| `omop_cdm_schema.json` | 22 OMOP CDM tables with columns, types, required flags, relationships, common join patterns, concept hierarchies, and example queries |
| `omop_validation_rules.json` | Required tables, required joins, and required columns for OMOP query validation |

## License

The original files are distributed under the MIT License. See the
[fastomop/omcp LICENSE](https://github.com/fastomop/omcp/blob/main/LICENSE) for details.
