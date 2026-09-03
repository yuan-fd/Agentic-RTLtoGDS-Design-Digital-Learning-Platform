# StateTune source admission record

`StateTune` is the project referred to as “StateTuner” in the planning
discussion.  Its public paper and repository are valuable L2 references, but
the checked revision has no `LICENSE`, `COPYING`, or `NOTICE` file even though
its README mentions a license.

Accordingly this directory records a pinned, read-only source audit only.  It
is not an executable plugin and is deliberately absent from the Runtime plugin
registry.  The platform must obtain a declared license or permission before
copying, modifying, redistributing, or adapting its source.  The same applies
to its RAG-EDA dependency and any model/provider credentials.

The algorithmic integration target, after admission, is narrow: map Runtime
observations to StateTune's `history.jsonl`; map its typed memory, candidate
buffer, Pareto set and promotion decisions back to immutable platform
artifacts; keep all OpenROAD runs under the platform Runtime.  The platform
does not reimplement StateTune's qEHVI, multi-fidelity GP, kNN runtime model,
or knowledge-agent logic.
