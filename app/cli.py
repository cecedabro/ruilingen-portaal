"""Admin commands for the server shell, e.g. to get the first admin in without any mail:

    kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli admin-link "Your Name"
    kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli join-link
    kubectl -n ruilingen exec deploy/ruilingen -- python -m app.cli set-list halls "A;B;Overig"

`admin-link` creates the user if needed, makes them admin and prints a one-time login link
(valid 60 minutes). Open it on your phone; you stay logged in there.
"""

import sys

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import User
from app.services import appdata, invites, logins, members


def main(argv: list[str]) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        if argv[:1] == ["join-link"]:
            print(invites.url(settings, invites.main_link(db)))
            return 0
        if argv[:1] == ["set-list"] and len(argv) == 3 and argv[1] in appdata.DEFAULT_LISTS:
            print("\n".join(appdata.set_list(db, argv[1], argv[2].split(";"))))
            return 0
        if argv[:1] == ["admin-link"] and len(argv) == 2:
            name = members.clean_name(argv[1])
            user = db.scalar(select(User).where(func.lower(User.name) == name.lower()))
            if user is None:
                user = User(name=name)
                db.add(user)
            user.is_admin = True
            user.is_active = True
            db.commit()
            print(logins.make_link(db, settings, user, minutes=60))
            return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
