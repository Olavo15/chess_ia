from io import StringIO
from datetime import datetime
import os
import time
import uuid

from flask import Flask, render_template, request, jsonify, session
import chess
import chess.pgn

from engine.ai_player import choose_move
from engine.memory import init_db, learn_from_game, record_game, get_conn

app = Flask(__name__)

# Em produção: use SECRET_KEY do .env/plataforma
# Em dev local: gera uma padrão para não quebrar o app
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Estado temporário por sessão.
# Bom para hobby/protótipo, mas não substitui banco persistente.
games = {}

init_db()


# =========================
# GAME STORAGE PER SESSION
# =========================
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


# =========================
# HELPERS
# =========================
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


# =========================
# LEARNING
# =========================
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

    print("SALVANDO PARTIDA:", result)
    print("TOTAL EXPERIÊNCIAS IA:", len(ai_experiences))

    try:
        record_game(result, pgn_text)
    except Exception as e:
        print("ERRO AO SALVAR PARTIDA:", e)

    # Em produção, evita timeout no checkmate
    # Aprendizado limitado só para não travar a resposta
    try:
        if ai_experiences:
            limited_experiences = ai_experiences[-20:]  # pode testar 10, 20 ou 30

            if result == "0-1":
                learn_from_game(limited_experiences, "win")
                print("IA aprendeu: vitória")
            elif result == "1-0":
                learn_from_game(limited_experiences, "loss")
                print("IA aprendeu: derrota")
            else:
                learn_from_game(limited_experiences, "draw")
                print("IA aprendeu: empate")
        else:
            print("Nenhuma experiência da IA para aprender")
    except Exception as e:
        print("ERRO AO APRENDER:", e)

    game["finished_processed"] = True
    game["ai_experiences"] = []

    return result


def apply_learning_self_play(board, history, experiences_by_side):
    if not board.is_game_over():
        return None

    result = board.result()
    pgn_text = build_pgn_from_history(history, result=result, self_play=True)
    record_game(result, pgn_text)

    if result == "1-0":
        if experiences_by_side["white"]:
            learn_from_game(experiences_by_side["white"], "win")
        if experiences_by_side["black"]:
            learn_from_game(experiences_by_side["black"], "loss")
    elif result == "0-1":
        if experiences_by_side["white"]:
            learn_from_game(experiences_by_side["white"], "loss")
        if experiences_by_side["black"]:
            learn_from_game(experiences_by_side["black"], "win")
    else:
        if experiences_by_side["white"]:
            learn_from_game(experiences_by_side["white"], "draw")
        if experiences_by_side["black"]:
            learn_from_game(experiences_by_side["black"], "draw")

    return result


def run_self_play_game(depth=2, max_moves=150):
    training_board = chess.Board()
    training_history = []
    training_ai_experiences = {
        "white": [],
        "black": [],
    }

    move_count = 0

    while not training_board.is_game_over() and move_count < max_moves:
        side = "white" if training_board.turn == chess.WHITE else "black"

        ai_move, exp = choose_move(training_board, depth=depth, use_memory=True)
        if ai_move is None:
            break

        san = training_board.san(ai_move)
        training_board.push(ai_move)

        training_history.append(move_to_dict(ai_move, san))
        if exp:
            training_ai_experiences[side].extend(exp)
        move_count += 1

    result = apply_learning_self_play(
        training_board,
        training_history,
        training_ai_experiences,
    )

    if result is None:
        result = training_board.result() if training_board.is_game_over() else "*"

    return {
        "result": result,
        "moves": len(training_history),
        "final_fen": training_board.fen(),
    }


# =========================
# ROUTES
# =========================
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
            ai_move, exp = choose_move(board, depth=1, use_memory=False)

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
        import traceback

        print("ERRO NA ROTA /move:", e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/train_self_play", methods=["POST"])
def train_self_play():
    try:
        data = request.get_json(silent=True) or {}

        games_to_train = min(max(int(data.get("games", 10)), 1), 50)
        depth = min(max(int(data.get("depth", 2)), 1), 5)

        results = []
        for _ in range(games_to_train):
            results.append(run_self_play_game(depth=depth))

        return jsonify(
            {
                "status": "ok",
                "trained_games": len(results),
                "results": results[-5:],
            }
        )
    except Exception as e:
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

        if isinstance(games_row, dict):
            games_count = games_row["total"]
            memory_count = memory_row["total"]
        else:
            games_count = (
                games_row["total"] if "total" in games_row.keys() else games_row[0]
            )
            memory_count = (
                memory_row["total"] if "total" in memory_row.keys() else memory_row[0]
            )

        return jsonify(
            {
                "saved_games": games_count,
                "learned_positions": memory_count,
                "database": "postgres" if os.environ.get("DATABASE_URL") else "sqlite",
            }
        )
    finally:
        conn.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
