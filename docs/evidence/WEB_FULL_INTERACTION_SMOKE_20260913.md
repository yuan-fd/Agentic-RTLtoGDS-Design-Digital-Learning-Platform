# Web full interaction smoke — 2026-09-13

A real Firefox Playwright run was performed against `http://127.0.0.1:8795` in
internal no-auth mode. The script clicked each primary navigation entry and
checked the corresponding page became active:

- Frontend Design → `#frontend`
- Backend Design → `#backend`
- Projects & Results → `#projects`
- Self-Evolution → `#evolution`
- Tutorial → `#tutorial`

Frontend and Backend pages were also checked with visibility assertions. No
network requests failed and no uncaught JavaScript exception occurred. Firefox
reported one expected CSP warning for the optional external Google Fonts URL;
the local font fallbacks and all controls remain usable.

The internal startup script now defaults `OPENROAD_PLATFORM_NO_AUTH=1`; this
is deliberate for the current private test deployment. Authentication can be
restored by setting `OPENROAD_PLATFORM_NO_AUTH=0` before startup.
