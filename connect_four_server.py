import asyncio

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

