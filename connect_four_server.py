import asyncio
import websockets
import json
import logging
import threading
import http.server
import socketserver
import os


GAME_HOST = '0.0.0.0'
GAME_PORT = 8765
WEB_PORT = 8000

BOARD_ROWS = 6
BOARD_COLS = 7
EMPTY_SLOT = ' '
PLAYERS = {}
restart_votes = set()
game_lock = asyncio.Lock()
game_active = False

# --- Game State ---
current_player_symbol = 'X'
game_board = [[EMPTY_SLOT for _ in range(BOARD_COLS)] for _ in range(BOARD_ROWS)]

logging.basicConfig(level=logging.INFO)


def run_web_server():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    with socketserver.TCPServer(("", WEB_PORT), QuietHandler) as httpd:
        print(f" Web server running. Access the game at: http://localhost:{WEB_PORT}")
        httpd.serve_forever()


def initialize_board():
    global game_board
    game_board = [[EMPTY_SLOT for _ in range(BOARD_COLS)] for _ in range(BOARD_ROWS)]


def to_json(message_type, data):
    return json.dumps({"type": message_type, "data": data})


async def broadcast_state(message_type, message_data):
    message = to_json(message_type, message_data)
    if PLAYERS:
        await asyncio.gather(*[conn.send(message) for conn in PLAYERS], return_exceptions=True)


def check_win(board, last_row, last_col, symbol):
    count = 0
    for r in range(BOARD_ROWS):
        if board[r][last_col] == symbol:
            count += 1
        else:
            count = 0
        if count == 4: return True

    count = 0
    for c in range(BOARD_COLS):
        if board[last_row][c] == symbol:
            count += 1
        else:
            count = 0
        if count == 4: return True

    for r in range(BOARD_ROWS - 3):
        for c in range(BOARD_COLS - 3):
            if board[r][c] == symbol and board[r + 1][c + 1] == symbol and board[r + 2][c + 2] == symbol and \
                    board[r + 3][c + 3] == symbol: return True
    for r in range(3, BOARD_ROWS):
        for c in range(BOARD_COLS - 3):
            if board[r][c] == symbol and board[r - 1][c + 1] == symbol and board[r - 2][c + 2] == symbol and \
                    board[r - 3][c + 3] == symbol: return True
    return False

