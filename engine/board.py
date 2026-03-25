import chess


class ChessGame:
    def __init__(self):
        self.board = chess.Board()

    def make_move(self, move_uci):
        move = chess.Move.from_uci(move_uci)

        if move not in self.board.legal_moves:
            raise Exception("Movimento ilegal")

        self.board.push(move)

    def get_board(self):
        board_matrix = []

        for rank in range(8, 0, -1):
            row = []
            for file in "abcdefgh":
                piece = self.board.piece_at(chess.parse_square(file + str(rank)))

                if piece:
                    color = "w" if piece.color else "b"
                    row.append(color + piece.symbol().lower())
                else:
                    row.append(None)

            board_matrix.append(row)

        return board_matrix

    def is_game_over(self):
        return self.board.is_game_over()

    def result(self):
        return self.board.result()
