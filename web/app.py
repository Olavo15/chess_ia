from io import StringIO
from datetime import datetime
import os
import time
import uuid
import traceback

from flask import Flask, render_template, request, jsonify, session
import chess
import chess.pgn

from engine.ai_player import choose_move
from engine.memory import (
    init_db,
    get_conn,
    record_game,
    learn_from_game,
    enqueue_learning_job,
    get_next_pending_job,
    mark_job_processing,
    mark_job_done,
    mark_job_failed,
    get_job_counts,
    normalize_experiences,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

games = {}

init_db()


def cleanup_games(max_age_seconds=1800):
    now = time.time()
    expired = []

    for game_id, game in list(games.items()):
        last_access = game.get("last_access", now)
        if now - last_access > max_age_seconds:
            expired.append(game_id)

    for game_id in expired:
        del games[game_id]


def get_game():
    cleanup_games()

    game_id = session.get("game_id")
    if not game_id:
        game_id = str(uuid.uuid4())
        session["game_id"] = game_id

    if game_id not in games:
        games[game_id] = {
            "board": chess.Board(),
            "move_history": [],
            "ai_experiences": [],
            "finished_processed": False,
            "last_access": time.time(),
        }

    games[game_id]["last_access"] = time.time()
    return games[game_id]


def move_to_dict(move: chess.Move, san: str):
    return {
        "uci": move.uci(),
        "san": san,
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
    }


def game_status_payload(board: chess.Board):
    status = None
    winner = None

    if board.is_checkmate():
        status = "checkmate"
        winner = "white" if board.turn == chess.BLACK else "black"
    elif board.is_check():
        status = "check"
    elif board.is_stalemate():
        status = "stalemate"
    elif board.is_insufficient_material():
        status = "draw"
    elif board.is_seventyfive_moves() or board.is_fivefold_repetition():
        status = "draw"

    return {
        "game_status": status,
        "winner": winner,
        "result": board.result() if board.is_game_over() else "*",
    }


def build_pgn_from_history(history, result="*", self_play=False):
    game = chess.pgn.Game()

    game.headers["Event"] = "Chess IA"
    game.headers["Site"] = (
        "Local" if not os.environ.get("DATABASE_URL") else "Production"
    )
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    game.headers["Round"] = str((len(history) + 1) // 2)

    if self_play:
        game.headers["White"] = "AI White"
        game.headers["Black"] = "AI Black"
    else:
        game.headers["White"] = "Player"
        game.headers["Black"] = "Chess IA"

    game.headers["Result"] = result

    node = game
    temp_board = chess.Board()

    for item in history:
        move = chess.Move.from_uci(item["uci"])
        if move in temp_board.legal_moves:
            node = node.add_variation(move)
            temp_board.push(move)

    exporter = StringIO()
    print(game, file=exporter, end="\n")
    return exporter.getvalue()


def build_success_message(job_type, result, learned_count, saved_game=True):
    return (
        f"[LEARNING][SUCCESS] "
        f"type={job_type} "
        f"result={result} "
        f"saved_game={saved_game} "
        f"learned_positions={learned_count}"
    )


def apply_learning_if_game_over(game):
    board = game["board"]
    move_history = game["move_history"]
    ai_experiences = game["ai_experiences"]

    if not board.is_game_over():
        return None

    if game["finished_processed"]:
        return board.result()

    result = board.result()
    pgn_text = build_pgn_from_history(move_history, result=result, self_play=False)

    enqueue_learning_job(
        "player_vs_ai",
        {
            "result": result,
            "pgn_text": pgn_text,
            "ai_experiences": list(ai_experiences),
        },
    )

    print(
        f"[LEARNING][ENQUEUED] "
        f"type=player_vs_ai "
        f"result={result} "
        f"experiences={len(ai_experiences)}"
    )

    game["finished_processed"] = True
    game["ai_experiences"] = []

    return result


def process_one_learning_job():
    job = get_next_pending_job()
    if not job:
        return {
            "processed": False,
            "message": "[LEARNING] Nenhum job pendente",
        }

    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"]

    try:
        mark_job_processing(job_id)

        if job_type == "player_vs_ai":
            result = payload["result"]
            pgn_text = payload["pgn_text"]
            ai_experiences = normalize_experiences(payload.get("ai_experiences", []))

            record_game(result, pgn_text)

            learned_count = 0
            if ai_experiences:
                if result == "0-1":
                    learned_count = learn_from_game(ai_experiences, "win")
                elif result == "1-0":
                    learned_count = learn_from_game(ai_experiences, "loss")
                else:
                    learned_count = learn_from_game(ai_experiences, "draw")

            success_message = build_success_message(
                job_type="player_vs_ai",
                result=result,
                learned_count=learned_count,
                saved_game=True,
            )
            print(success_message)
            mark_job_done(job_id, success_message)

            return {
                "processed": True,
                "job_id": job_id,
                "status": "done",
                "message": success_message,
            }

        raise ValueError(f"job_type inválido: {job_type}")

    except Exception as e:
        error_message = (
            f"[LEARNING][ERROR] job_id={job_id} type={job_type} error={str(e)}"
        )
        print(error_message)
        traceback.print_exc()
        mark_job_failed(job_id, error_message)

        return {
            "processed": True,
            "job_id": job_id,
            "status": "failed",
            "message": error_message,
        }


def train_self_play_batch(games_to_train=10, depth=1, max_moves=150):
    aggregated_white = []
    aggregated_black = []
    results = []

    for _ in range(games_to_train):
        training_board = chess.Board()
        training_history = []
        training_ai_experiences = {
            "white": [],
            "black": [],
        }

        move_count = 0

        while not training_board.is_game_over() and move_count < max_moves:
            side = "white" if training_board.turn == chess.WHITE else "black"

            ai_move, exp = choose_move(
                training_board,
                depth=depth,
                use_memory=False,
                exploration_rate=0.15,
            )
            if ai_move is None:
                break

            san = training_board.san(ai_move)
            training_board.push(ai_move)

            training_history.append(move_to_dict(ai_move, san))
            if exp:
                training_ai_experiences[side].extend(exp)

            move_count += 1

        result = training_board.result() if training_board.is_game_over() else "*"
        pgn_text = build_pgn_from_history(
            training_history, result=result, self_play=True
        )

        record_game(result, pgn_text)

        if result == "1-0":
            aggregated_white.extend(training_ai_experiences["white"])
            aggregated_black.extend(training_ai_experiences["black"])
            white_outcome = "win"
            black_outcome = "loss"
        elif result == "0-1":
            aggregated_white.extend(training_ai_experiences["white"])
            aggregated_black.extend(training_ai_experiences["black"])
            white_outcome = "loss"
            black_outcome = "win"
        else:
            aggregated_white.extend(training_ai_experiences["white"])
            aggregated_black.extend(training_ai_experiences["black"])
            white_outcome = "draw"
            black_outcome = "draw"

        results.append(
            {
                "result": result,
                "moves": len(training_history),
                "final_fen": training_board.fen(),
                "white_outcome": white_outcome,
                "black_outcome": black_outcome,
            }
        )

    learned_count = 0

    white_norm = normalize_experiences(aggregated_white)
    black_norm = normalize_experiences(aggregated_black)

    if white_norm:
        white_results = [r["white_outcome"] for r in results]
        if white_results.count("win") >= max(
            white_results.count("loss"), white_results.count("draw")
        ):
            learned_count += learn_from_game(white_norm, "win")
        elif white_results.count("loss") >= white_results.count("draw"):
            learned_count += learn_from_game(white_norm, "loss")
        else:
            learned_count += learn_from_game(white_norm, "draw")

    if black_norm:
        black_results = [r["black_outcome"] for r in results]
        if black_results.count("win") >= max(
            black_results.count("loss"), black_results.count("draw")
        ):
            learned_count += learn_from_game(black_norm, "win")
        elif black_results.count("loss") >= black_results.count("draw"):
            learned_count += learn_from_game(black_norm, "loss")
        else:
            learned_count += learn_from_game(black_norm, "draw")

    print(
        f"[LEARNING][SUCCESS] type=self_play_batch saved_game=True "
        f"trained_games={len(results)} learned_positions={learned_count}"
    )

    return results, learned_count


@app.route("/")
def index():
    game = get_game()

    return render_template(
        "index.html",
        fen=game["board"].fen(),
        history=game["move_history"],
    )


@app.route("/health")
def health():
    return (
        jsonify(
            {
                "status": "ok",
                "environment": (
                    "production" if os.environ.get("DATABASE_URL") else "development"
                ),
                "database": "postgres" if os.environ.get("DATABASE_URL") else "sqlite",
                "jobs": get_job_counts(),
            }
        ),
        200,
    )


@app.route("/legal_moves")
def legal_moves():
    game = get_game()
    board = game["board"]

    square = request.args.get("square", "").strip()
    if not square:
        return jsonify([])

    try:
        sq = chess.parse_square(square)
    except ValueError:
        return jsonify([])

    moves = []
    for move in board.legal_moves:
        if move.from_square == sq:
            moves.append(
                {
                    "from": square,
                    "to": chess.square_name(move.to_square),
                    "promotion": (
                        chess.piece_symbol(move.promotion) if move.promotion else None
                    ),
                    "capture": board.is_capture(move),
                }
            )

    return jsonify(moves)


@app.route("/move", methods=["POST"])
def move():
    try:
        game = get_game()
        board = game["board"]
        move_history = game["move_history"]
        ai_experiences = game["ai_experiences"]

        move_str = request.form.get("move", "").strip()

        if not move_str:
            return jsonify({"status": "illegal", "message": "Movimento vazio"}), 400

        try:
            move = chess.Move.from_uci(move_str)
        except ValueError:
            return jsonify({"status": "illegal", "message": "UCI inválido"}), 400

        if move not in board.legal_moves:
            return jsonify({"status": "illegal", "message": "Movimento ilegal"}), 400

        player_san = board.san(move)
        board.push(move)
        player_move_data = move_to_dict(move, player_san)
        move_history.append(player_move_data)

        final_result = apply_learning_if_game_over(game)

        ai_move_data = None
        if not board.is_game_over():
            ai_move, exp = choose_move(
                board,
                depth=2,
                use_memory=True,
                memory_weight=12.0,
                exploration_rate=0.03,
            )

            if ai_move is not None:
                ai_san = board.san(ai_move)
                board.push(ai_move)
                ai_move_data = move_to_dict(ai_move, ai_san)
                move_history.append(ai_move_data)

                if exp:
                    ai_experiences.extend(exp)

            final_result = apply_learning_if_game_over(game)

        payload = {
            "status": "ok",
            "fen": board.fen(),
            "history": move_history,
            "last_move": move_history[-1] if move_history else None,
            "player_move": player_move_data,
            "ai_move": ai_move_data,
            "saved_result": final_result,
        }
        payload.update(game_status_payload(board))

        return jsonify(payload)

    except Exception as e:
        print("ERRO NA ROTA /move:", e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/train_self_play", methods=["POST"])
def train_self_play():
    try:
        data = request.get_json(silent=True) or {}

        games_to_train = min(max(int(data.get("games", 10)), 1), 30)
        depth = min(max(int(data.get("depth", 1)), 1), 2)

        results, learned_count = train_self_play_batch(
            games_to_train=games_to_train,
            depth=depth,
        )

        return jsonify(
            {
                "status": "ok",
                "trained_games": len(results),
                "learned_positions": learned_count,
                "results": results[-5:],
                "jobs": get_job_counts(),
            }
        )
    except Exception as e:
        print("ERRO NA ROTA /train_self_play:", e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/auto_train", methods=["POST"])
def auto_train():
    try:
        data = request.get_json(silent=True) or {}

        games_to_train = min(max(int(data.get("games", 10)), 1), 30)
        depth = min(max(int(data.get("depth", 1)), 1), 2)
        process_limit = min(max(int(data.get("process_limit", 10)), 1), 50)

        results, learned_count = train_self_play_batch(
            games_to_train=games_to_train,
            depth=depth,
        )

        processed_results = []
        for _ in range(process_limit):
            outcome = process_one_learning_job()
            processed_results.append(outcome)
            if not outcome["processed"]:
                break

        return jsonify(
            {
                "status": "ok",
                "trained_games": len(results),
                "self_play_learned_positions": learned_count,
                "last_training_results": results[-5:],
                "processed_jobs": processed_results,
                "jobs": get_job_counts(),
            }
        )
    except Exception as e:
        print("ERRO NA ROTA /auto_train:", e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/process_learning_jobs", methods=["POST"])
def process_learning_jobs():
    try:
        data = request.get_json(silent=True) or {}
        limit = min(max(int(data.get("limit", 1)), 1), 50)

        results = []
        for _ in range(limit):
            outcome = process_one_learning_job()
            results.append(outcome)
            if not outcome["processed"]:
                break

        return jsonify(
            {
                "status": "ok",
                "processed_runs": len(results),
                "results": results,
                "job_counts": get_job_counts(),
            }
        )
    except Exception as e:
        print("ERRO NA ROTA /process_learning_jobs:", e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/reset", methods=["POST"])
def reset():
    game = get_game()
    game["board"] = chess.Board()
    game["move_history"] = []
    game["ai_experiences"] = []
    game["finished_processed"] = False
    game["last_access"] = time.time()

    payload = {
        "status": "ok",
        "fen": game["board"].fen(),
        "history": game["move_history"],
        "last_move": None,
        "player_move": None,
        "ai_move": None,
        "saved_result": None,
    }
    payload.update(game_status_payload(game["board"]))
    return jsonify(payload)


@app.route("/debug_memory")
def debug_memory():
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS total FROM games")
        games_row = cur.fetchone()

        cur.execute("SELECT COUNT(*) AS total FROM move_memory")
        memory_row = cur.fetchone()

        cur.execute("SELECT COALESCE(SUM(plays), 0) AS total FROM move_memory")
        plays_row = cur.fetchone()

        if isinstance(games_row, dict):
            games_count = games_row["total"]
            memory_count = memory_row["total"]
            total_learn_events = plays_row["total"]
        else:
            games_count = games_row[0]
            memory_count = memory_row[0]
            total_learn_events = plays_row[0]

        return jsonify(
            {
                "saved_games": games_count,
                "learned_positions": memory_count,
                "total_learn_events": total_learn_events,
                "database": "postgres" if os.environ.get("DATABASE_URL") else "sqlite",
                "jobs": get_job_counts(),
            }
        )
    finally:
        conn.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
