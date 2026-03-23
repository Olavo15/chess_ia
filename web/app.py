from flask import Flask, render_template, request, jsonify
import chess
import random

app = Flask(__name__)

board = chess.Board()
move_history = []


def choose_move(current_board: chess.Board):
    moves = list(current_board.legal_moves)
    if not moves:
        return None
    return random.choice(moves)


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
    global board, move_history

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
        ai_move = choose_move(board)
        if ai_move is not None:
            ai_san = board.san(ai_move)
            board.push(ai_move)
            ai_move_data = move_to_dict(ai_move, ai_san)
            move_history.append(ai_move_data)

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


@app.route("/reset", methods=["POST"])
def reset():
    global board, move_history
    board = chess.Board()
    move_history = []
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
    app.run(debug=True)