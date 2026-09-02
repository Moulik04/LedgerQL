# Schema

Populated in Phase 1. This document is injected into the SQL-generation
prompt, so it must stay accurate and tight: every table, every column,
its type, and 2-3 example values. Nothing here should describe a column
that doesn't exist in the live DuckDB database.

Per the checkpoint rule in the master prompt: **do not change this schema
after Phase 1 without stopping to ask MJ first.**
