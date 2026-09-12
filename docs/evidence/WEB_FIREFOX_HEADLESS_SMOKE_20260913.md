# Firefox headless browser smoke — 2026-09-13

System Firefox successfully rendered the live platform at `http://127.0.0.1:8795/`
and produced `web-firefox-headless-20260913.png`. The page shows the three main
entries (Labs, EDA Console, Learn with Ibex) and the plain white/blue visual style.
The host emitted GLX/EGL diagnostic warnings, but the screenshot was generated.
This is a live unauthenticated page-render proof; authenticated Runtime replay
remains a separate gate.
