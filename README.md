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

### Hosting on Render

The QR automatically uses Render's `RENDER_EXTERNAL_URL` to open the public HTTPS `/join` page,
without adding the server's internal `PORT`. For a custom domain, set `PUBLIC_URL` to the public
base URL, e.g. `https://quiz.example.com` (no `/join` or internal port).

If an existing deployment's QR does not open registration, set `PUBLIC_URL` in Render's environment
settings to `https://<your-service>.onrender.com`, redeploy, then refresh the QR screen and scan again.
Hosted participants do not need to be on the server's Wi-Fi network.

## Event flow

1. Project `/` – participants scan the QR, register on `/join` and wait on a "get ready" screen.
2. Watch the live count on `/admin/registrations`. When every team has joined, press **Approve & start quiz**
   (duration is editable). Registration closes at that moment and all phones start together.
3. Every team gets the **same fixed sequence**: one easy, one medium, one tough, then repeat (Q1 easy, Q2 medium,
   Q3 tough, Q4 easy, …). Questions are shown one at a time with no feedback after answering.
   The server times each question from the moment it is shown until the answer arrives (a refresh does not reset it).
4. When time is up (or **End round now** in `/admin`) participants see a thank-you screen; the admin sees scores,
   correctness and time taken per question, and can export `Leaderboard CSV` / `Answers CSV`.
   **Review all team answers** unlocks on the dashboard after the round ends (including the 1.5-second
   network grace period), or once every registered team answers all questions. The admin-only
   `/admin/review` page shows each team's questions, submitted and correct answers in both languages,
   correctness, server-measured time, base points, bonus and total points for evaluation concerns.
5. **New round** in `/admin` clears answers, keeps the teams and reopens registration.

## Scoring (edit the constants at the top of `app.py`, admin-only)

* Correct: **+10**
* Bonus: **+5** for a correct answer submitted in **5 seconds or less** (**+15** total).
  There is no bonus for a wrong answer.
* Wrong: **−5**. Unanswered questions: **0**.
* Ranking: higher score → more correct answers → lower total time on correct answers

Existing submitted answers are automatically rescored using these rules on the first startup
after deployment. Answers and their recorded times are preserved; leaderboard and CSV totals
use the recalculated points.

## Questions

50 bilingual (Kannada + English) questions across 10 themes live in `questions_data.py`, each tagged `easy`,
`medium` or `tough` (17 / 17 / 16). The quiz order is generated from those tags (easy → medium → tough, repeating, with
themes spread out). Edit that file and restart: if no answers exist yet the new bank loads automatically; otherwise run
`python app.py --reseed` (this also clears all answers). The admin **Questions** page shows each question's position,
difficulty and correct answer.

Three easy and three medium questions have been refreshed with more challenging history, geography,
literature and Yakshagana questions; the difficulty counts and fixed order are unchanged.
If answers already exist, export results before reseeding for the next event. A new round clears
answers; restart the app afterward to load the refreshed bank without removing registered teams.

For a large crowd you can serve with waitress: `pip install waitress` then `waitress-serve --port 5000 app:app`.
