"""Everything HTTP: sessions, rendering, and the routes (in `routes/`).

Routes stay thin: read the form, call a service, then redirect (POST → redirect → GET) or
render a template. Business rules live in `app.services`.
"""
