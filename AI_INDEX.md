# AI_INDEX

Deterministic routing table. Pick ROUTE_ID by task keywords → read only the listed CANON
sections → query the Atlas slice. No prose here.

| ROUTE_ID | SELECTORS | CANON | ATLAS_QUERY |
|---|---|---|---|
| MINER | run, search, idea card, github collect | CANON-01,CANON-11 | --component miner |
| CHALLENGE | challenge, daemon, key scheduler, promotion | CANON-02,CANON-08 | --component challenge |
| CLI | command, parser, handler, dispatch, exit code | CANON-03 | --component cli |
| CORE_BUILD | factory-build, gate, golden, harness, desk | CANON-04,CANON-10 | --route core_factory_build |
| CONTINUATION | factory-continue, patch, queue, failure type | CANON-05,CANON-10 | --route continuation |
| SPEC_REPAIR | spec repair, golden fix, anti-hardcode | CANON-05,CANON-10 | --route spec_repair |
| PRODUCTIZATION | review, polish, editor, interaction ui, draft execution, viewer | CANON-06,CANON-11 | --route productization_chain |
| CLOSED_LOOP | autopilot, judge, lane, gap, HOLD, evidence | CANON-07,CANON-10,CANON-11 | --route factory_closed_loop |
| STORAGE | db, run layout, artifact root, run kind | CANON-08 | --component storage |
| DASHBOARD | dashboard, presentation, read model, label | CANON-09 | --component dashboard |
| VALIDATION | factory-validate, marker, validator registry | CANON-10 | --route factory_validate |
| SECURITY | secret, redaction, frozen, invariant | CANON-11 | --component support |
| ARCHITECTURE | atlas, structure, fingerprint, context, check | CANON-12 | --component atlas |
