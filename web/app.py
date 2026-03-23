from io import StringIO

from flask import Flask, render_template, request, jsonify
import chess
import chess.pgn

from engine.ai_player import choose_move
from engine.memory import init_db, learn_from_game, record_game

app = Flask(__name__)

board = chess.Board()
move_history = []
ai_experiences = []

init_db()


def move_to_dict(move: chess.Move, san: str):
    return {
        "uci": move.uci(),
        "san": san,
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
    }


def game_status_payload(current_board: chess.Board):
    status = None
    winner = None

    if current_board.is_checkmate():
        status = "checkmate"
        winner = "white" if current_board.turn == chess.BLACK else "black"
    elif current_board.is_check():
        status = "check"
    elif current_board.is_stalemate():
        status = "stalemate"
    elif current_board.is_insufficient_material():
        status = "draw"

    return {
        "game_status": status,
        "winner": winner,
        "result": current_board.result() if current_board.is_game_over() else "*",
    }


def build_pgn_from_history(history):
    game = chess.pgn.Game()
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


def apply_learning_if_game_over(current_board, current_history, current_ai_experiences):
    if not current_board.is_game_over():
        return None

    result = current_board.result()
    pgn_text = build_pgn_from_history(current_history)
    record_game(result, pgn_text)

    # IA joga dos dois lados no self-play:
    # brancas recebem win se 1-0, pretas recebem win se 0-1
    if result == "1-0":
        learn_from_game(current_ai_experiences["white"], "win")
        learn_from_game(current_ai_experiences["black"], "loss")
    elif result == "0-1":
        learn_from_game(current_ai_experiences["white"], "loss")
        learn_from_game(current_ai_experiences["black"], "win")
    else:
        learn_from_game(current_ai_experiences["white"], "draw")
        learn_from_game(current_ai_experiences["black"], "draw")

    return result


def run_self_play_game(depth=2, max_moves=200):
    training_board = chess.Board()
    training_history = []
    training_ai_experiences = {
        "white": [],
        "black": [],
    }

    move_count = 0

    while not training_board.is_game_over() and move_count < max_moves:
        side = "white" if training_board.turn == chess.WHITE else "black"

        ai_move, exp = choose_move(training_board, depth=depth)
        if ai_move is None:
            break

        san = training_board.san(ai_move)
        training_board.push(ai_move)

        training_history.append(move_to_dict(ai_move, san))
        training_ai_experiences[side].append(exp)

        move_count += 1

    result = apply_learning_if_game_over(
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


@app.route("/")
def index():
    return render_template(
        "index.html",
        fen=board.fen(),
        history=move_history,
    )


@app.route("/legal_moves")
def legal_moves():
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
                    "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
                }
            )

    return jsonify(moves)


@app.route("/move", methods=["POST"])
def move():
    global board, move_history, ai_experiences

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

    ai_move_data = None
    if not board.is_game_over():
        ai_move, exp = choose_move(board, depth=2)

        if ai_move is not None:
            ai_san = board.san(ai_move)
            board.push(ai_move)
            ai_move_data = move_to_dict(ai_move, ai_san)
            move_history.append(ai_move_data)
            ai_experiences.append(exp)

    payload = {
        "status": "ok",
        "fen": board.fen(),
        "history": move_history,
        "last_move": move_history[-1] if move_history else None,
        "player_move": player_move_data,
        "ai_move": ai_move_data,
    }
    payload.update(game_status_payload(board))

    return jsonify(payload)


@app.route("/train_self_play", methods=["POST"])
def train_self_play():
    data = request.get_json(silent=True) or {}
    games = int(data.get("games", 10))
    depth = int(data.get("depth", 2))

    results = []
    for _ in range(games):
        results.append(run_self_play_game(depth=depth))

    return jsonify({
        "status": "ok",
        "trained_games": games,
        "results": results,
    })


@app.route("/reset", methods=["POST"])
def reset():
    global board, move_history, ai_experiences

    board = chess.Board()
    move_history = []
    ai_experiences = []

    payload = {
        "status": "ok",
        "fen": board.fen(),
        "history": move_history,
        "last_move": None,
        "player_move": None,
        "ai_move": None,
    }
    payload.update(game_status_payload(board))
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)