# RIM AI ENTRYPOINT

Machine-first repository map for AI coding agents (Claude/GPT).
RIM = Repo Idea Miner + Challenge Mode + Product Factory. Runtime UI(dashboard/viewer)는
제품 기능이며 이 문서의 대상이 아니다.

## REQUIRED READ ORDER
1. `REENTRY.md` — current state and open blockers
2. `AI_INDEX.md` — pick the CANON-ID + Atlas selector for the task
3. Selected `PROJECT_CANON.md` sections (never the whole file)
4. architecture-context query — initial code scope (see CONTEXT COMMAND)
5. read the actual `read_first` files/symbols, then decide the final edit scope

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
```bash
python -m repo_idea_miner architecture-context --canon CANON-07
python -m repo_idea_miner architecture-context --route factory_closed_loop --impact
python -m repo_idea_miner architecture-context --changed --impact
```
selectors: `--canon/--component/--route/--module/--symbol/--cli/--artifact/--changed`
(복수 허용, `--compact`=line format, 출력은 결정론적 JSON)
`--changed`는 `git status --porcelain -uall` 정본 — untracked 파일 포함
(Atlas에 없는 새 production py는 UNKNOWN_PENDING_BUILD로 표시)

## VALIDATION COMMANDS
```bash
python -m pytest -q                                   # full suite
python -m repo_idea_miner architecture-check          # structure + doc governance
python -m repo_idea_miner factory-validate <run_dir>  # product run artifacts
python -m repo_idea_miner validate <run_dir>          # miner run artifacts
```

## REQUIRED BEFORE EDIT (full contract in CANON-12)
- check context `invariants` / `contracts` / `do_not_modify` / `tests_to_run`;
  use `--impact` for the direct static impact when needed
- Atlas does not finalize edit scope — context membership is a reading hint, not an edit list
- files absent from the context may still be required: confirm via actual call sites/contracts

## REQUIRED AFTER EDIT
1. targeted tests → 2. `architecture-context --changed --impact` → 3. `architecture-check`
4. structural change: `architecture-build` (same commit) / semantic·contract·invariant
   change: related PROJECT_CANON section / state change: `REENTRY.md`

## DO NOT
- commit `.env`, `challenge.db`, `runs/` contents, raw prompts/logs
- create new root markdown or human-facing documentation
- weaken golden/fixture/contract to pass gates
- bypass spec-repair §8 protection with automation
- report unverified work as complete
