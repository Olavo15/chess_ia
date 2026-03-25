import json
import random
import os

Q_TABLE_FILE = "data/q_table.json"

if os.path.exists(Q_TABLE_FILE):
    with open(Q_TABLE_FILE, "r") as f:
        Q_TABLE = json.load(f)
else:
    Q_TABLE = {}


def save_q_table():
    with open(Q_TABLE_FILE, "w") as f:
        json.dump(Q_TABLE, f)


def get_state(board):
    return board.fen()


def choose_action(board, epsilon=0.2):
    state = get_state(board)
    moves = list(board.legal_moves)

    if random.random() < epsilon or state not in Q_TABLE:
        return random.choice(moves)

    return max(moves, key=lambda m: Q_TABLE[state].get(str(m), 0))


def update_q(state, action, reward, next_state, alpha=0.1, gamma=0.9):
    if state not in Q_TABLE:
        Q_TABLE[state] = {}

    if str(action) not in Q_TABLE[state]:
        Q_TABLE[state][str(action)] = 0

    max_future = 0
    if next_state in Q_TABLE and Q_TABLE[next_state]:
        max_future = max(Q_TABLE[next_state].values())

    current = Q_TABLE[state][str(action)]

    Q_TABLE[state][str(action)] = current + alpha * (
        reward + gamma * max_future - current
    )
