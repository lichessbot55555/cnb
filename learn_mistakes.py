"""Find the bot's blunders in its recent games and remember them in the mistake book.

The games are downloaded from the Lichess API, because BotLi does not write PGN files.
Every position where the bot gave away more than `--threshold` centipawns compared to the
engine's best move is stored together with the move it should have played. The live bot
then skips those exact moves.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.request

import chess
import chess.engine
import chess.pgn
import chess.variant
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mistake_book import MistakeBook  # noqa: E402

VARIANT_KEYS = {
    "Standard": "standard",
    "From Position": "standard",
    "Chess960": "chess960",
    "Atomic": "atomic",
    "Horde": "horde",
    "Crazyhouse": "crazyhouse",
    "Antichess": "antichess",
    "King of the Hill": "kingofthehill",
    "Racing Kings": "racingkings",
    "Three Check": "3check",
}


def board_class_for(variant_name: str):
    """Return the python-chess board class for a lichess variant name."""
    if variant_name in ("Standard", "From Position"):
        return chess.Board
    return chess.variant.find_variant(variant_name)


def engine_for(config: dict, variant_name: str) -> str:
    """Return the engine binary this variant uses in the BotLi config."""
    key = VARIANT_KEYS.get(variant_name, "standard")
    engines = config.get("engines") or {}
    section = engines.get(key) or engines.get("standard") or {}
    return os.path.join(section.get("dir", "./engines"), section.get("name", "stockfish"))


def download_games(username: str, token: str, max_games: int) -> str:
    """Return the PGN of the bot's most recent games."""
    url = (f"https://lichess.org/api/games/user/{username}"
           f"?max={max_games}&moves=true&clocks=false&evals=false&opening=false")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/x-chess-pgn",
        "User-Agent": "botli-mistake-learner",
    })
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8", "replace")


def evaluate(engine, board, played, depth: int, width: int):
    """Return (best_move, best_score, played_score) for one position."""
    infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=width)
    best_score = best_move = played_score = None
    for info in infos:
        pv = info.get("pv")
        if not pv:
            continue
        score = info["score"].pov(board.turn).score(mate_score=100000)
        if score is None:
            continue
        if best_score is None:
            best_score, best_move = score, pv[0]
        if pv[0] == played:
            played_score = score
    if best_score is None:
        return None, None, None
    if played_score is None:
        info = engine.analyse(board, chess.engine.Limit(depth=depth), root_moves=[played])
        if not info or "score" not in info:
            return None, None, None
        played_score = info["score"].pov(board.turn).score(mate_score=100000)
    return best_move, best_score, played_score


def learn(username: str, book_path: str, config_path: str,
          depth: int, threshold: int, width: int, max_games: int) -> None:
    """Analyse the games and write the mistakes into the book."""
    config = yaml.safe_load(open(config_path, encoding="utf-8")) or {}
    token = str(config.get("token") or "").strip()
    if not token:
        print("No token in the config, cannot download games.")
        return

    book = MistakeBook(book_path)
    before = len(book)
    try:
        pgn = download_games(username, token, max_games)
    except Exception as error:  # noqa: BLE001
        print(f"Could not download the games: {error}")
        return

    engines: dict[str, chess.engine.SimpleEngine] = {}
    games = 0
    for block in re.split(r"\n\s*\n(?=\[Event )", pgn):
        game = chess.pgn.read_game(io.StringIO(block))
        if game is None:
            continue
        variant_name = game.headers.get("Variant", "Standard")
        white, black = game.headers.get("White", ""), game.headers.get("Black", "")
        if username not in (white, black):
            continue
        bot_is_white = white == username
        path = engine_for(config, variant_name)
        if not os.path.isfile(path):
            print(f"  skipping {variant_name}: no engine at {path}")
            continue
        if path not in engines:
            engine = chess.engine.SimpleEngine.popen_uci(path)
            engine.configure({"Threads": 2, "Hash": 256})
            engines[path] = engine
        engine = engines[path]

        board = board_class_for(variant_name)()
        try:
            for move in game.mainline_moves():
                if board.turn == bot_is_white:
                    best, best_score, played_score = evaluate(engine, board, move, depth, width)
                    if best is not None and played_score is not None and best != move:
                        loss = best_score - played_score
                        if loss >= threshold:
                            book.record(board, move, best, loss)
                            print(f"  blunder {move.uci()} -> {best.uci()} "
                                  f"(-{loss} cp) in {game.headers.get('Site')}")
                board.push(move)
        except (ValueError, AssertionError) as error:
            print(f"  skipping a game: {error}")
            continue
        games += 1

    for engine in engines.values():
        engine.close()
    book.save()
    print(f"analysed {games} games, mistakes {before} -> {len(book)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--book", default="mistakes.json")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--threshold", type=int, default=150)
    ap.add_argument("--width", type=int, default=4)
    ap.add_argument("--max-games", type=int, default=40)
    a = ap.parse_args()
    learn(a.username, a.book, a.config, a.depth, a.threshold, a.width, a.max_games)