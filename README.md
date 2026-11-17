# ಕನ್ನಡ ರಾಜ್ಯೋತ್ಸವ 2026 – Fastest Finger First Quiz

Flask + SQLite quiz for Kannada Rajyotsava 2026. Teams scan a QR code, register a team name and answer
as many Karnataka / Kannada questions as they can in one timed round (default 5 minutes). The server
records the time taken for every question. Participants never see correctness, timings or scores:
all results are visible to the admin only.

## Run

```powershell
pip install -r requirements.txt
python app.py
```

The console prints the URLs (the IP is your laptop's Wi-Fi IP; phones must be on the same network):

| Page | URL | Who |
|------|-----|-----|
| QR screen (QR only, project it) | `http://<ip>:5000/` | Everyone |
| Registration form (the QR opens this) | `http://<ip>:5000/join` | Participants |
| Registrations monitor + approve & start | `http://<ip>:5000/admin/registrations` | Quiz master |
| Control panel, live leaderboard, per-question times, CSV export | `http://<ip>:5000/admin` | Quiz master |
| Question bank: all 50 questions with options and correct answers (search / theme filter) | `http://<ip>:5000/admin/questions` | Quiz master |

Admin password: `karnataka2026` (override with the `ADMIN_PASSWORD` environment variable).
Other optional variables: `PORT`, `PUBLIC_URL` (force the host encoded in the QR, e.g. behind a tunnel), `SECRET_KEY`.

## Event flow

1. Project `/` – participants scan the QR, register on `/join` and wait on a "get ready" screen.
2. Watch the live count on `/admin/registrations`. When every team has joined, press **Approve & start quiz**
   (duration is editable). Registration closes at that moment and all phones start together.
3. Every team gets the **same fixed sequence**: one easy, one medium, one tough, then repeat (Q1 easy, Q2 medium,
   Q3 tough, Q4 easy, …). Questions are shown one at a time with no feedback after answering.
   The server times each question from the moment it is shown until the answer arrives (a refresh does not reset it).
4. When time is up (or **End round now** in `/admin`) participants see a thank-you screen; the admin sees scores,
   correctness and time taken per question, and can export `Leaderboard CSV` / `Answers CSV`.
5. **New round** in `/admin` clears answers, keeps the teams and reopens registration.

## Scoring (edit the constants at the top of `app.py`, admin-only)

* Correct: **+100** plus a speed bonus of up to **+50** (shrinks linearly to 0 over 15 s)
* Wrong: **−10**
* Ranking: higher score → more correct answers → lower total time on correct answers

## Questions

50 bilingual (Kannada + English) questions across 10 themes live in `questions_data.py`, each tagged `easy`,
`medium` or `tough` (17 / 17 / 16). The quiz order is generated from those tags (easy → medium → tough, repeating, with
themes spread out). Edit that file and restart: if no answers exist yet the new bank loads automatically; otherwise run
`python app.py --reseed` (this also clears all answers). The admin **Questions** page shows each question's position,
difficulty and correct answer.

For a large crowd you can serve with waitress: `pip install waitress` then `waitress-serve --port 5000 app:app`.
