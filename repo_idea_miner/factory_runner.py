# factory 명령 본체: challenge.db에서 승격 대상 스캔 → Product Factory 순차 실행 (--once/--max-runs/--continuous).
from __future__ import annotations

import time
from pathlib import Path

from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
from repo_idea_miner.config import Settings, load_challenge_miner_settings, load_settings
from repo_idea_miner.factory_db import challenge_has_run, log_product_event, open_factory_db
from repo_idea_miner.factory_pipeline import (
    FactorySettings,
    load_challenge_from_db,
    load_factory_settings,
    run_product_factory,
)
from repo_idea_miner.factory_schemas import promotion_line


def eligible_challenges(conn, limit: int = 20) -> list[dict]:
    """Auto Promotion Gate(§6)를 통과하고 아직 run이 없는 challenge 목록.

    owner가 Dashboard에서 RETRY를 누른 run만 있는 challenge는 다시 대상이 된다 (§5).
    """
    rows = conn.execute(
        "SELECT id, final_label, owner_clarity_score, artifact_dir FROM challenges "
        "WHERE final_label IN ('GOOD_CHALLENGE', 'STEAL_ONLY') "
        "ORDER BY score_total DESC, id ASC LIMIT ?",
        (limit * 5,),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        if len(out) >= limit:
            break
        if challenge_has_run(conn, row["id"]):
            continue
        try:
            challenge = load_challenge_from_db(conn, row["id"])
        except (OSError, ValueError, KeyError):
            continue
        line, _ = promotion_line(challenge["card"], challenge.get("owner_clarity_score"))
        if line is None:
            continue
        challenge["line"] = line
        out.append(challenge)
    return out


def run_factory(
    db_path: str | Path = "challenge.db",
    mode: str = "mock",
    output_dir: str | Path = "runs",
    max_runs: int = 1,
    continuous: bool = False,
    poll_seconds: float = 30.0,
    settings: Settings | None = None,
    factory_settings: FactorySettings | None = None,
    llm=None,
    max_cycles: int | None = None,
) -> dict:
    """factory 명령 진입점. 기본은 안전 모드(max_runs 제한), --continuous를 명시해야 계속 돈다 (§19.1).

    Challenge daemon과 같은 challenge.db의 api_keys 테이블을 key 상태 저장소로 공유한다 (§12).
    """
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    conn = open_factory_db(db_path)
    scheduler = None
    if mode == "live" and llm is None:
        keys = settings.google_keys
        if not keys:
            conn.close()
            raise ValueError("live 모드인데 GOOGLE_API_KEY_*가 없습니다.")
        scheduler = ChallengeKeyScheduler(conn, keys, load_challenge_miner_settings())

    summary = {"mode": mode, "runs": [], "processed": 0, "errors": 0, "continuous": continuous}
    cycles = 0
    try:
        while True:
            cycles += 1
            if scheduler is not None:
                scheduler.maybe_daily_reset()
            remaining = None if continuous else max_runs - summary["processed"]
            batch_limit = 10 if remaining is None else max(remaining, 0)
            if batch_limit == 0:
                break
            batch = eligible_challenges(conn, limit=batch_limit)
            if not batch:
                log_product_event(conn, None, "factory_idle", "승격 대상 challenge 없음")
                if not continuous:
                    break
                time.sleep(poll_seconds)
                if max_cycles is not None and cycles >= max_cycles:
                    break
                continue
            for challenge in batch:
                res = run_product_factory(
                    challenge,
                    mode=mode,
                    output_dir=output_dir,
                    db_conn=conn,
                    settings=settings,
                    factory_settings=fset,
                    scheduler=scheduler,
                    llm=llm,
                )
                summary["runs"].append(
                    {
                        "challenge_id": challenge.get("challenge_id"),
                        "run_dir": res.get("run_dir"),
                        "verdict": res.get("verdict"),
                        "line": res.get("line"),
                        "ok": res.get("ok"),
                        "error": res.get("error"),
                    }
                )
                summary["processed"] += 1
                if res.get("error"):
                    summary["errors"] += 1
                if not continuous and summary["processed"] >= max_runs:
                    break
            if not continuous and summary["processed"] >= max_runs:
                break
            if max_cycles is not None and cycles >= max_cycles:
                break
            if continuous:
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        log_product_event(conn, None, "factory_stop", "중지 요청")
    finally:
        conn.close()
    return summary
