# Teaching migration: route inventory

Generated from the inherited HTTP dispatchers; route literals/regexes below are a discovery index, not a complete OpenAPI specification. L1 suffix dispatch is listed separately. No route is deleted by this inventory.

| Dispatcher | Method | Line | Route / regex |
| --- | --- | ---: | --- |
| `apps/api/app.py` | GET | 4707 | `/api/auth/session` |
| `apps/api/app.py` | GET | 4709 | `/api/health` |
| `apps/api/app.py` | GET | 4726 | `/api/platform` |
| `apps/api/app.py` | GET | 4740 | `/api/platform/results` |
| `apps/api/app.py` | GET | 4754 | `/api/developer/users` |
| `apps/api/app.py` | GET | 4759 | `/api/platform/evolution` |
| `apps/api/app.py` | GET | 4763 | `/api/extensions/edacraft` |
| `apps/api/app.py` | GET | 4765 | `/api/extensions/rtlscout` |
| `apps/api/app.py` | GET | 4767 | `/api/projects` |
| `apps/api/app.py` | GET | 4769 | `/api/designs` |
| `apps/api/app.py` | GET | 4775 | `/api/designs/examples` |
| `apps/api/app.py` | GET | 4777 | `/api/rtl/specs/[^/]+/lineage` |
| `apps/api/app.py` | GET | 4782 | `/api/designs/[^/]+/schematic\.svg` |
| `apps/api/app.py` | GET | 4788 | `/api/designs/[^/]+/module\.svg` |
| `apps/api/app.py` | GET | 4794 | `/api/designs/[^/]+/source` |
| `apps/api/app.py` | GET | 4803 | `/api/designs/[^/]+/design-ir` |
| `apps/api/app.py` | GET | 4809 | `/api/designs/` |
| `apps/api/app.py` | GET | 4811 | `/api/designs/` |
| `apps/api/app.py` | GET | 4814 | `/api/runs` |
| `apps/api/app.py` | GET | 4818 | `/api/runtime/runs` |
| `apps/api/app.py` | GET | 4825 | `/api/runtime/runs/[^/]+/artifacts/[^/]+/excerpt` |
| `apps/api/app.py` | GET | 4833 | `/api/runtime/runs/[^/]+/artifacts/[^/]+` |
| `apps/api/app.py` | GET | 4839 | `/api/runtime/runs/[^/]+/evidence-ir` |
| `apps/api/app.py` | GET | 4843 | `/api/runtime/runs/[^/]+/edair` |
| `apps/api/app.py` | GET | 4848 | `/api/runtime/runs/([^/]+)/learning-evidence` |
| `apps/api/app.py` | GET | 4855 | `/api/runtime/runs/` |
| `apps/api/app.py` | GET | 4857 | `/api/runtime/runs/` |
| `apps/api/app.py` | GET | 4859 | `/api/knowledge/public` |
| `apps/api/app.py` | GET | 4861 | `/api/taiwei/technology-matrix` |
| `apps/api/app.py` | GET | 4863 | `/api/export/si2` |
| `apps/api/app.py` | GET | 4865 | `/api/agent/traces` |
| `apps/api/app.py` | GET | 4867 | `/api/agent/traces/` |
| `apps/api/app.py` | GET | 4869 | `/api/agent/traces/` |
| `apps/api/app.py` | GET | 4871 | `/api/learning/observations` |
| `apps/api/app.py` | GET | 4875 | `/api/v2/closed-loops` |
| `apps/api/app.py` | GET | 4890 | `/api/v2/external-optimizer-loops` |
| `apps/api/app.py` | GET | 4896 | `/api/v2/external-optimizer-loops/` |
| `apps/api/app.py` | GET | 4898 | `/api/v2/external-optimizer-loops/` |
| `apps/api/app.py` | GET | 4904 | `/api/v2/closed-loops/` |
| `apps/api/app.py` | GET | 4906 | `/api/v2/closed-loops/` |
| `apps/api/app.py` | GET | 4912 | `/api/spec/sessions/[^/]+` |
| `apps/api/app.py` | GET | 4916 | `/api/runs/` |
| `apps/api/app.py` | GET | 4918 | `/api/runs/` |
| `apps/api/app.py` | POST | 4932 | `/api/auth/login` |
| `apps/api/app.py` | POST | 4932 | `/api/auth/register` |
| `apps/api/app.py` | POST | 4958 | `/api/auth/logout` |
| `apps/api/app.py` | POST | 5001 | `/api/spec/sessions` |
| `apps/api/app.py` | POST | 5004 | `/api/craft/plans` |
| `apps/api/app.py` | POST | 5007 | `/api/extensions/taiwei/run` |
| `apps/api/app.py` | POST | 5016 | `/api/extensions/edacraft/([^/]+)/smoke` |
| `apps/api/app.py` | POST | 5021 | `/api/extensions/edacraft/([^/]+)/run` |
| `apps/api/app.py` | POST | 5029 | `/api/spec/sessions/([^/]+)/turn` |
| `apps/api/app.py` | POST | 5034 | `/api/spec/sessions/([^/]+)/materialize-spec` |
| `apps/api/app.py` | POST | 5040 | `/api/rtl/specs/([^/]+)/run-to-baseline` |
| `apps/api/app.py` | POST | 5046 | `/api/v2/external-optimizer-loops` |
| `apps/api/app.py` | POST | 5051 | `/api/v2/external-optimizer-loops/([^/]+)/advance` |
| `apps/api/app.py` | POST | 5058 | `/api/research/protocols` |
| `apps/api/app.py` | POST | 5061 | `/api/research/compare-arms` |
| `apps/api/app.py` | POST | 5064 | `/api/designs/import` |
| `apps/api/app.py` | POST | 5073 | `/api/designs/([^/]+)/circuitops-export` |
| `apps/api/app.py` | POST | 5079 | `/api/runs/([^/]+)/cancel` |
| `apps/api/app.py` | POST | 5086 | `/api/runtime/runs/([^/]+)/cancel` |
| `apps/l1_workbench/server.py` | POST | 27 | `/api/l1/sessions` |

## L1 suffix commands

answers, execute, parameters, m1-proposal, candidates, m1-compare, l2-upgrade, l2-escalate, l2-configure, l2-advance, queries, knowledge, artifacts, stages, advance, cancel, recover; GET teaching, events, l2-campaigns. Source: apps/l1_workbench/server.py.

## Migration ownership

| Family | Current caller / owner | Treatment |
| --- | --- | --- |
| spec / rtl / designs | apps/web/assets/app.js → ApiState → DesignService + RTLFrontendStore + Runtime | ACTIVE capability; extract RTL use cases incrementally |
| runtime/runs + artifacts | web + acceptance runners → WorkflowRuntime | ACTIVE authority; use for experiment dashboard |
| l1 sessions | terminal_dashboard.py → server.py → WorkbenchService | ACTIVE baseline/candidate/control; share use cases with web |
| v2 external optimizer writes | retired handler; old controller launcher still exists | LEGACY; never revive retired checkpoints |
| v2 closed loops / research | old web + scientific harnesses | LEGACY product interface; reuse audited data/optimizer components for new experiment contract |
| extensions/taiwei, edacraft | optional old web / specialized scripts | outside teaching core; preserve independently |
| auth | existing internal/research auth paths | preserve existing behavior; no new administration scope |

Endpoint-specific caller migration evidence must accompany each extraction; no whole-family deletion is authorized merely by this table.
