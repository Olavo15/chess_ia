import random

def choose_move(board):
    moves = list(board.legal_moves)
    return random.choice(moves)