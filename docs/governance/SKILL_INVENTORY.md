# Skill infrastructure inventory

Audit date: 2026-08-30  
Scope: research-plugin intake, paper reproduction, bounded refactoring, and
experiment/provenance discipline.  This document is an intake record, **not**
an installation record.  No third-party skill was installed or executed during
this audit.

## Review method

Every candidate was checked in this order: source, license, maintainer/project
identity, scope, security implications, compatibility with this repository,
and an exact commit.  A skill is not permitted to download or execute upstream
code, modify protected evaluation inputs, or replace the platform's plugin
contract.  Exact content review remains mandatory immediately before any
future installation because a skill can contain executable instructions.

## Installed

| Skill | Status | Reason |
| --- | --- | --- |
| None beyond the environment-provided system skills | No external installation performed | This phase authorizes assessment only.  Installing a skill changes the Codex environment and must follow a reviewed, pinned source decision. |

The official curated catalog was queried on 2026-08-30.  It contains useful
general skills such as `security-best-practices`, `security-threat-model`,
`define-goal`, and `jupyter-notebook`, but no EDA-specific upstream-plugin or
paper-reproduction package.

## Candidates retained for narrow future review

| Candidate | Frozen source | License / maintainer | Useful narrow scope | Compatibility and security conclusion |
| --- | --- | --- | --- | --- |
| OpenAI curated skills | `openai/skills@49f948faa9258a0c61caceaf225e179651397431` | Official OpenAI repository; GitHub API did not provide a repository-level SPDX value at audit time | Goal definition, notebook work, security review | Candidate only at the individual-skill level.  Do not install the whole repository; inspect the chosen skill's own files and license notice first. |
| Superpowers | `obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797` | MIT; `obra` | Bounded planning, debugging, and verification discipline | Candidate as a *reference* for local process.  Its broad prescriptive workflow must not override this repository's slice budget, protected evaluator, or external-plugin rules.  Do not execute bundled automation before file-by-file review. |
| PhD Skills | `fcakyon/phd-skills@8d642d3e114ee1d1e4d000f918d71e9bf0453dc2` | MIT; `fcakyon` | `reproduce` and `paper-verification` checklists | Candidate as a reference for paper → official repo → environment → smoke → evidence.  Its fallback advice for recreating missing implementations/data is incompatible here: if upstream source or license is missing, this platform must stop rather than invent a substitute. |

## Not admitted now

| Candidate | Frozen source | Status | Reason |
| --- | --- | --- | --- |
| PaperReproduction-Skills | `yyccbb/PaperReproduction-Skills@d6148aa4ad48d5b493b40e7dc0ca436e09dc9bb2` | Not admitted | MIT is declared, but the project is very new and the audit has not established sufficient maintainer, maintenance, or security evidence for a repository-wide installation.  It may be re-reviewed only for a specific required workflow. |
| New local repository skill | N/A | Deferred | A local skill is justified only after the intake review shows a durable gap.  The current need is policy documentation, not more executable workflow machinery. |

## Required future installation record

Any later admission must append: requested use case, exact directory within the
source repository, checked file digest, license evidence, maintainer/source
link, changed Codex destination, human authorization, and a statement that no
remote script has been executed.  It must also name the corresponding project
rule in `AGENTS.md`.

## Sources

- Official catalog: `https://github.com/openai/skills` and the curated listing
  retrieved with the environment-provided `skill-installer` helper.
- Superpowers: `https://github.com/obra/superpowers`.
- PhD Skills: `https://github.com/fcakyon/phd-skills`.
- PaperReproduction-Skills: `https://github.com/yyccbb/PaperReproduction-Skills`.

