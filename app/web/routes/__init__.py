"""One APIRouter per area; main.py includes them all.

public     /, /healthz, /privacy, /theme
auth       /login, /join/<code>, /login/<token>, /email/<token>, /logout
board      /aangeboden, /gezocht, /mijn, /meldingen
listings   /plaatsen and the actions on listings and reactions
account    /account (name, notification email, devices, delete)
admin      /beheer (invite links, members, lists, mail template, removing shifts)
"""

from app.web.routes import account, admin, auth, board, listings, public

ROUTERS = [public.router, auth.router, board.router, listings.router, account.router, admin.router]
