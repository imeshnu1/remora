# Viavios — real deployable source code

> Public brand: **Viavios** (viavios.com — "the way of life"). "Remora" is the internal codename; the GitHub repo keeps the name `imeshnu1/remora`.

Viavios is a web app where anybody can create an account and write their own
memoir, legacy book, chronicle, or testament: free writing in chapters, photos,
voice notes, a life timeline, and letters — with private / family / public /
testament sharing, reader voting on public stories, an opt-in for publishers,
PDF export, and paid plans.

This folder is the **real codebase** (not a hosted prototype). You can run it
locally and upload the same files to AWS.

## Stack
- Python **FastAPI** backend, **SQLAlchemy** database (SQLite by default;
  PostgreSQL on AWS via `DATABASE_URL`)
- Vanilla HTML/CSS/JS frontend in `static/` — served by FastAPI, **no build step**
- Passwords hashed with PBKDF2 (Python stdlib), cookie/session auth
- PDF export with fpdf2

## Run it locally (exact commands)

```bash
cd remora/app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 in a browser.
Health check: http://localhost:8000/health should return `{"ok": true, "app": "remora"}`.

On Windows, activate the venv with `venv\Scripts\activate` instead.

Optional settings: copy `.env.example` values into real environment variables
(`DATABASE_URL`, `UPLOAD_DIR`, `SESSION_SECRET`, `PORT`). Defaults work with no setup:
SQLite file `remora.db` and an `uploads/` folder are created automatically.

## Photos in this repo

The story/hero JPEGs that live in `static/img/` at runtime travel through the
GitHub push pipeline as plain base64 **text** files in `static/img_b64/`
(`<name>.jpg.b64`), because that pipeline carries UTF-8 text only — the binary
JPEGs cannot be pushed directly. `decode_photos.py` (stdlib only, idempotent)
decodes every `.b64` file back into `static/img/<name>.jpg`. Render runs it
automatically as part of the build command. After a **local clone**, run it
once before starting the server:

```bash
python3 decode_photos.py
```

## Upload to AWS (App Runner — simplest test run)

**Option A — Docker / App Runner from a container image**
1. Build and push the image (needs an ECR repository named `remora`):
   ```bash
   aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
   docker build -t remora .
   docker tag remora:latest <account>.dkr.ecr.<region>.amazonaws.com/remora:latest
   docker push <account>.dkr.ecr.<region>.amazonaws.com/remora:latest
   ```
2. In the AWS Console → App Runner → Create service → Source: Container registry (ECR) → pick the `remora` image.
3. Port: `8000`. Environment variables: set `SESSION_SECRET` to a long random string.
   For a durable database add `DATABASE_URL` pointing at RDS (step below); without it the
   app uses SQLite inside the container, which is fine for a first test run but is wiped on redeploy.
4. Deploy. App Runner gives you an HTTPS URL — that is your live test run.

**Option B — GitHub → App Runner source deploy**
Push this `app/` folder to a GitHub repo (GitHub is the source of truth in Imesh's
pipeline; pushing needs his one-time PAT). In App Runner choose "Source code repository",
connect the repo, runtime Python 3, build command `pip install -r requirements.txt`,
start command `uvicorn main:app --host 0.0.0.0 --port 8000`.

**Durable database (when moving past the test run)**
1. RDS → Create database → PostgreSQL, db name `remora`.
2. Set in App Runner: `DATABASE_URL=postgresql://remora:<password>@<rds-endpoint>:5432/remora`
3. Redeploy. Tables are created automatically on startup.
Uploaded photos/audio currently live in the container's `uploads/` folder; for a
multi-instance production deployment, move `UPLOAD_DIR` to shared storage (EFS) or
switch media to S3 — noted here honestly; SQLite/single-container is the test-run shape.

## Monetization (built in)
- **Free:** 1 book, chapters/timeline/letters/uploads, Private + Family sharing, in-app reading.
- **Paid gates enforced in code:** creating a 2nd book returns an upgrade prompt (HTTP 402);
  **PDF export** and **Testament sharing setup** also require a paid plan.
- **Plans:** Keeper Monthly ($9/mo), Keeper Yearly ($79/yr), Lifetime Legacy one-time ($249).
- **Checkout is simulated** in this codebase (`POST /api/checkout` just sets the user's plan).
  For real launch, replace that endpoint with **Stripe** Checkout + a Stripe webhook that
  sets `users.plan` on payment — the plan names (`subscription_monthly`,
  `subscription_yearly`, `lifetime`) are already the values stored in the DB.
- Other revenue already modelled: print-book margin (future fulfilment) and a platform
  commission on publisher deals — a book is only visible to publishers when the author
  toggles **"Open to publishers"** on a public book; reader votes rank that list.

## Sensible defaults chosen (no questions asked)
- Free-tier gate = 1 book + no PDF + no testament setup (all three enforced).
- Letters are visible only to the book owner in this version.
- Testament books stay owner-only until a real-world death-verification/release
  process is designed — recipients and a release note are stored now.
- Family sharing = the signed-in user's email must be in the book's family email list.
- One vote per signed-in user per public book (enforced by a DB unique constraint).

## File tree
```
app/
  main.py            FastAPI backend: auth, books, chapters, media, timeline,
                     letters, discover, voting, publishers, plans, checkout, PDF
  requirements.txt
  Dockerfile
  .env.example
  README.md
  static/
    index.html
    style.css
    app.js           Entire frontend (auth, editor, discover, pricing, reader)
  uploads/           Uploaded photos/audio land here at runtime
```

## Verified
The app was run locally with uvicorn and tested end-to-end (two users, privacy
separation, public discover + single vote, photo upload, PDF download, plan
upgrade, free-tier gate). See the handover notes from the build session for the
per-check results.
