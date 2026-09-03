# L1 external reuse source audit

Status: `SOURCE_AUDIT_ONLY` (2026-09-03)

This record permits reading the two projects below as architectural references.
It does **not** authorize installing, executing, vendoring, copying, or
registering either project as an OpenROAD Platform plugin.  Any later reuse of
code or execution surface must receive its own intake lock with native and
bounded platform smoke evidence.

## Candidates

| Candidate | Upstream / exact commit | License | Native entrypoint | Reuse decision |
| --- | --- | --- | --- | --- |
| Spec2GDS Agent | `https://github.com/appleweiping/spec2gds-agent`, `f115ca1605ab42c32815367d9eafe313e3597ae5` | Apache-2.0 code; separate CC-BY-4.0 content license | Python CLI plus project-owned subprocess tool adapters | Read architectural patterns only: contract-first manifests, retained failure evidence, conservative parsers. Do not reuse its Runtime, static dashboard, benchmark claims, provider path, or subprocess ownership. |
| agent-r2g skills | `https://github.com/ShenShan123/r2g-skills`, `11b0dad38e6e89e91c5a91de2c286a734124eae3` | MIT | Claude skill scripts and shell-based ORFS/signoff flows | Read workflow/checklist and stage-report organisation only. Do not install skills, execute bootstrap scripts, source environment files, or make them a platform plugin. |

## Why neither project is an executable L1 dependency

Both projects own process invocation and local workflow state.  The Platform
owns those boundaries through `TaskSpec`, `PluginManifest`, `WorkflowRuntime`,
the protected evaluator, artifact store, cancellation and durable trace.
Replacing that boundary would violate the thin-platform architecture and make
an LLM/skill script an ungoverned EDA-process owner.

The smallest potential future boundary is therefore not either project as a
whole: it is a reviewed, fixed-input parser or a documentation-only procedure
whose output is validated against the Platform's existing typed contracts.

## Reuse commitments for the L1 mainline

- Reuse the already admitted local ORFS/OpenROAD plugin for execution.
- Adapt only stable, schema-checked report facts into L1 query receipts.
- Keep raw ORFS reports and Runtime artifacts authoritative.
- Treat any future copied source, dependency installation, skill registration
  or external executable as a new intake decision under `AGENTS.md`.

## Review inputs

The source review used public repository metadata, README and selected source
files via the GitHub API.  No repository clone, script, package installer,
credential, network call from an external project, or external executable was
run as part of this audit.
