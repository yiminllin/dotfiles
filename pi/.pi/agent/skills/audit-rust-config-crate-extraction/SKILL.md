---
name: "audit-rust-config-crate-extraction"
description: "Audit whether extracting a Rust config/schema crate will actually be lightweight: hidden transitive dependencies from data types, Cargo regular/build dependency paths, pinned-revision dependency checks, and Cargo/Bazel packaging boundaries."
version: 1
created: "2026-10-12"
updated: "2026-10-12"
---
## When to Use
Use before proposing a lightweight configuration/data crate extraction, especially when a simple field type belongs to a large runtime/message crate. This is source analysis, not permission to compile, download, or change source.

## Procedure
1. Pin the source revision and read configuration structs, imports, conversion methods, loaders, validators, generated identifiers, registry lookup, Cargo manifests, and build rules.
2. Separate pure schema/local loading from cloud queries, downloads, runtime-model conversion, and pure helpers imported from heavyweight utility crates.
3. Follow each remaining type's defining crate through regular and build dependencies, including workspace-inherited paths. Record optional/target declarations, exclude dev dependencies unless relevant, and report missing manifests.
4. Compare candidate declared closures: unchanged schema, replacement of heavyweight small data types, and optional further data/runtime separation. Counts must exclude invented new crates and must not be presented as resolved feature graphs or performance gains.
5. Inspect build macros for injected Cargo-derived dependencies and preserve runfiles, environment variables, data files, generated enum behavior, and CLI derives.
6. Check compatibility: re-exported types preserve paths but changed public field types need conversion; moving a type out of its runtime crate prevents retaining its inherent methods there. Use caller-owned functions or extension traits deliberately.
7. Propose the smallest boundary that meets the agreed dependency budget. Preserve serialization and validation, and distinguish isolating one crate from making the entire consumer stack lightweight.
8. After an approved extraction, audit dependencies left in the old package. If cargo-shear is configured and execution is approved, use it as a candidate detector; confirm each finding against all remaining source and the approved targeted build scope before removing a dependency. A moved logging call can leave a dependency unused, but that historical pattern is not proof for another revision.

## Pitfalls
- One small data type can inherit cloud/download dependencies through its owning message crate.
- A narrow trait still inherits heavy dependencies if its return types belong to a heavy crate.
- External registry dependency names are not full transitive dependency counts; optional/target-inclusive manifest traversal is conservative, not a Cargo/Bazel configured graph.
- Cargo feature unification can re-enable optional runtime or CLI dependencies.
- Do not weaken schema validation or replace typed fields with opaque JSON solely to shrink dependencies.
- Do not run builds, dependency resolution, network operations, or source migrations without the required approval.

## Verification
1. Support important edges with pinned source/manifests and confirm all followed local manifests exist.
2. For an approved implementation, inspect selected-feature Cargo and Bazel graphs and prove prohibited dependency paths are absent.
3. Compare parsed configurations and generated output before/after; test field encoding, override precedence, identity fallback, and config discovery.
4. Measure build/image/binary costs separately if requested; do not infer them from dependency counts.