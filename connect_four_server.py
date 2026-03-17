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


def make_move(col, symbol):
    global game_board
    try:
        col = int(col)
        if not (0 <= col < BOARD_COLS): return False, "Invalid column.", -1
    except ValueError:
        return False, "Not a number.", -1

    for row_index in range(BOARD_ROWS - 1, -1, -1):
        if game_board[row_index][col] == EMPTY_SLOT:
            game_board[row_index][col] = symbol
            return True, row_index, col
    return False, "Column full.", -1


def is_board_full():
    return not any(EMPTY_SLOT in row for row in game_board)


async def send_turn_state():
    global current_player_symbol
    player_x = next((conn for conn, (sym, _) in PLAYERS.items() if sym == 'X'), None)
    player_o = next((conn for conn, (sym, _) in PLAYERS.items() if sym == 'O'), None)

    async def safe_send(conn, msg):
        try:
            await conn.send(msg)
        except:
            pass

    if player_x and player_o:
        msg_x = to_json("game_state", {"board": game_board, "player": "X", "turn": current_player_symbol,
                                       "status": "YOUR_TURN" if current_player_symbol == 'X' else f"Waiting for {current_player_symbol}"})
        msg_o = to_json("game_state", {"board": game_board, "player": "O", "turn": current_player_symbol,
                                       "status": "YOUR_TURN" if current_player_symbol == 'O' else f"Waiting for {current_player_symbol}"})
        await safe_send(player_x, msg_x)
        await safe_send(player_o, msg_o)


async def game_handler(websocket):
    global current_player_symbol, game_active, restart_votes
    async with game_lock:
        if len(PLAYERS) < 2:
            sym = 'X' if not any(s == 'X' for s, _ in PLAYERS.values()) else 'O'
            PLAYERS[websocket] = (sym, websocket.remote_address)
            await websocket.send(to_json("status", f"You are Player {sym}. Waiting..."))
            if len(PLAYERS) == 2:
                initialize_board()
                current_player_symbol = 'X'
                game_active = True
                restart_votes.clear()
                await broadcast_state("start", "Game starting!")
                await send_turn_state()
        else:
            await websocket.send(to_json("status", "Game full."))
            return

    sym = PLAYERS[websocket][0]
    try:
        async for message in websocket:
            data = json.loads(message)
            if data['type'] == 'move':
                async with game_lock:
                    if not game_active:
                        continue
                    if sym != current_player_symbol:
                        await websocket.send(to_json("error", "Not your turn."))
                        continue
                    success, r, c = make_move(data['column'], sym)
                    if success:
                        if check_win(game_board, r, c, sym):
                            game_active = False
                            await broadcast_state("game_over", {"message": f"Player {sym} WINS!", "board": game_board})
                            continue
                        if is_board_full():
                            game_active = False
                            await broadcast_state("game_over", {"message": "Draw!", "board": game_board})
                            continue
                        current_player_symbol = 'O' if sym == 'X' else 'X'
                        await send_turn_state()
            elif data['type'] == 'play_again':
                async with game_lock:
                    restart_votes.add(sym)
                    await broadcast_state("restart_vote", f"Player {sym} wants to play again ({len(restart_votes)}/2)")
                    if len(restart_votes) == 2:
                        initialize_board()
                        current_player_symbol = 'X'
                        game_active = True
                        restart_votes.clear()
                        await broadcast_state("start", "Game Restarted!")
                        await send_turn_state()
    except:
        pass
    finally:
        async with game_lock:
            if websocket in PLAYERS: del PLAYERS[websocket]
            if len(PLAYERS) == 1:
                game_active = False
                restart_votes.clear()
                await broadcast_state("opponent_left", {"message": "Opponent left.", "board": game_board})
                PLAYERS.clear()


async def main():
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    print(f" Game server running. Websocket port: {GAME_PORT}")
    async with websockets.serve(game_handler, GAME_HOST, GAME_PORT):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped.")