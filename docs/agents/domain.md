# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This is a single-context repo.

Use:

- `CONTEXT.md` at the repo root for project domain language and concepts.
- `docs/adr/` at the repo root for architectural decision records.

## Before exploring

Read `CONTEXT.md` when it exists. Read relevant ADRs from `docs/adr/` when they touch the area being changed.

If these files do not exist yet, proceed silently. Do not flag their absence or suggest creating them upfront. The domain-modeling workflows can create them later when terms or decisions actually need to be captured.

## Expected structure

```text
/
|-- CONTEXT.md
|-- docs/
|   `-- adr/
|       |-- 0001-example-decision.md
|       `-- 0002-example-decision.md
`-- src/
```

## Vocabulary

When output names a domain concept in an issue title, refactor proposal, hypothesis, test name, or implementation note, use the term as defined in `CONTEXT.md`.

If the concept is missing from the glossary, either avoid inventing new language or note it as a candidate for domain modeling.

## ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.
