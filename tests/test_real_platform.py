import json
from pathlib import Path

import pytest

from keno.collect import collect_rounds, parse_round_line
from keno.bot.datasource import iter_replay_rounds
from keno.game.keno_draw import draw_keno
from keno.provably_fair.float_generator import FloatGenerator
from keno.provably_fair.hmac_rng import HmacSha256Rng


def test_parse_round_line_accepts_commas_and_spaces():
    assert parse_round_line("12, 5, 33, 40, 1, 7, 18, 22, 29, 3") == [12, 5, 33, 40, 1, 7, 18, 22, 29, 3]
    assert parse_round_line("1 2 3 4 5 6 7 8 9 10") == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert parse_round_line("") is None


def test_parse_round_line_extracts_from_noisy_table_rows():
    # Timestamps, bet ids, amounts and multiplier columns must not break extraction.
    noisy = "2026-09-11 03:12:45  Keno  bet 518230401  0.00010000  12, 5, 33, 40, 1, 7, 18, 22, 29, 3"
    assert parse_round_line(noisy) == [12, 5, 33, 40, 1, 7, 18, 22, 29, 3]
    assert parse_round_line("round #99: 1 2 3 4 5 6 7 8 9 10 (x1.10)") == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_parse_round_line_rejects_bad_data():
    for bad in ["1,2,3", "1,2,3,4,5,6,7,8,9,10,11", "1,1,2,3,4,5,6,7,8,9", "0,1,2,3,4,5,6,7,8,41", "1;2;3"]:
        with pytest.raises(ValueError):
            parse_round_line(bad)


def test_collect_rounds_skips_bad_lines_and_reports(tmp_path, capsys):
    out = tmp_path / "manual.jsonl"
    accepted = collect_rounds(out, ["1, 2, 3, 4, 5, 6, 7, 8, 9, 10", "garbage line", "2 3 4 5 6 7 8 9 10 11 12"])
    assert accepted == 1
    captured = capsys.readouterr().out
    assert "skipped line 2" in captured
    assert "skipped line 3" in captured
    rounds = list(iter_replay_rounds(out))
    assert len(rounds) == 1


def test_collect_rounds_writes_valid_jsonl(tmp_path):
    out = tmp_path / "manual.jsonl"
    accepted = collect_rounds(out, ["1, 2, 3, 4, 5, 6, 7, 8, 9, 10", "", "10 20 30 40 9 19 29 39 8 18", "done", "should not appear"])
    assert accepted == 2
    rounds = list(iter_replay_rounds(out))
    assert len(rounds) == 2
    assert rounds[0].numbers == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert rounds[0].source == "manual"
    assert rounds[1].round_id == "1"


def test_verify_rounds_against_own_engine_end_to_end(tmp_path):
    """Generate rounds with our engine, log them, then verify with the same seeds.

    This is the same flow used against the real platform: reveal the server seed,
    log the drawn numbers, and require local_result == real_result for every round.
    """
    server_seed, client_seed = "real-platform-server-seed", "real-platform-client-seed"
    out = tmp_path / "manual.jsonl"
    lines = []
    with out.open("w", encoding="utf-8") as f:
        for nonce in range(5):
            rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce=nonce, cursor=0))
            numbers = draw_keno(rng)
            line = json.dumps({"type": "round", "round_id": str(nonce), "timestamp": "2026-09-11T00:00:00+00:00", "numbers": numbers, "server_seed": server_seed, "client_seed": client_seed, "nonce": nonce, "source": "manual"})
            f.write(line + "\n")
            lines.append(",".join(str(n) for n in numbers))
    assert len(lines) == 5

    from keno.cli import main

    import sys

    argv = sys.argv
    sys.argv = ["keno", "verify-rounds", "--replay-file", str(out), "--server-seed", server_seed, "--client-seed", client_seed, "--start-nonce", "0"]
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    finally:
        sys.argv = argv


def test_verify_rounds_fails_on_tampered_log(tmp_path, capsys):
    server_seed, client_seed = "sv", "cl"
    rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce=0, cursor=0))
    numbers = draw_keno(rng)
    tampered = [n + 1 if n < 40 else 1 for n in numbers]
    out = tmp_path / "manual.jsonl"
    out.write_text(json.dumps({"type": "round", "round_id": "0", "timestamp": "2026-09-11T00:00:00+00:00", "numbers": tampered, "source": "manual"}) + "\n", encoding="utf-8")
    from keno.cli import main

    import sys

    argv = sys.argv
    sys.argv = ["keno", "verify-rounds", "--replay-file", str(out), "--server-seed", server_seed, "--client-seed", client_seed, "--start-nonce", "0"]
    try:
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
    finally:
        sys.argv = argv


def test_collect_from_multiline_text_block(tmp_path):
    """Simulates one clipboard paste covering several history rows at once."""
    from keno.collect import collect_rounds

    out = tmp_path / "clip.jsonl"
    block = "3, 15, 22, 31, 4, 18, 27, 36, 9, 12\n7 8 9 10 11 12 13 14 15 16\n\n19, 20, 21, 22, 23, 24, 25, 26, 27, 28"
    accepted = collect_rounds(out, block.splitlines())
    assert accepted == 3
    rounds = list(iter_replay_rounds(out))
    assert [r.round_id for r in rounds] == ["0", "1", "2"]
    assert rounds[2].numbers == [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
