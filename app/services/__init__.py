"""Business rules: everything that reads or changes data, with no HTTP in it.

Each module covers one part of the domain. Functions take a SQLAlchemy `Session` and raise
`UserError` (with a Dutch message for the user) when a rule is broken. Writes that may race
with other users go through `transaction.run_write`.

    board          what the boards show: open listings, filters, the day picker
    listings       posting, reacting, confirming, withdrawing, removing a shift
    invites        invite links (the group-chat link and extra links)
    logins         one-time login links and email verification
    members        names, admin role, deleting members
    appdata        settings admins edit at runtime (zaal/werkplek lists, mail template)
    planning       the email to planning for a completed swap
    housekeeping   deleting old data
    transaction    run_write (retry on SQLite write conflicts) and the notification outbox
"""
