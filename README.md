# RIM AI ENTRYPOINT

Machine-first repository map for AI coding agents (Claude/GPT).
RIM = Repo Idea Miner + Challenge Mode + Product Factory. Runtime UI(dashboard/viewer)는
제품 기능이며 이 문서의 대상이 아니다.

## READ ORDER
1. `REENTRY.md` — current state packet
2. `AI_INDEX.md` — deterministic routing table
3. Selected `PROJECT_CANON.md` sections (never the whole file)
4. architecture-context query — Atlas slice (see CONTEXT COMMAND)

## REPOSITORY RULES
- main branch only. commit per semantic unit, push immediately. no force push/rebase.
- do not modify Miner core: `pipeline.py`, `search_pipeline.py`, `schemas.py`
- do not expose secrets (`.env`: `GOOGLE_API_KEY_1..11`, `GITHUB_TOKEN`)
- do not modify base runs (`runs/**` of a judged run is immutable — child runs only)
- observe fresh results before trusting recorded reports
- structural change commit must update PROJECT_CANON + rebuild atlas in the same commit

## SETUP
- Python >= 3.11, `pip install -e .`
- CLI entrypoint: `python -m repo_idea_miner <command>` (`.cli` 직접 실행은 무출력)
- env names: `GOOGLE_API_KEY_1..11`, `GITHUB_TOKEN`, `RIM_GEMMA_MODEL`, `RIM_FACTORY_USE_DOCKER`

## CONTEXT COMMAND
```text
architecture-context --canon CANON-07
architecture-context --route factory_closed_loop
architecture-context --changed --impact
```

## VALIDATION COMMANDS
```bash
python -m pytest -q                                   # full suite
python -m repo_idea_miner architecture-check          # structure + doc governance
python -m repo_idea_miner factory-validate <run_dir>  # product run artifacts
python -m repo_idea_miner validate <run_dir>          # miner run artifacts
```

## AI PROTOCOL (short form — full rules in CANON-12)
before edit: `architecture-context --impact` → invariants → do_not_modify → tests_to_run
after edit: targeted tests → `architecture-context --changed --impact` → `architecture-check`
→ structural change: `architecture-build` / semantic change: PROJECT_CANON / state change: REENTRY

## DO NOT
- commit `.env`, `challenge.db`, `runs/` contents, raw prompts/logs
- create new root markdown or human-facing documentation
- weaken golden/fixture/contract to pass gates
- bypass spec-repair §8 protection with automation
- report unverified work as complete
