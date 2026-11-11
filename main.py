"""
Remora - memoir / legacy book / chronicle / testament web app.
FastAPI + SQLAlchemy (SQLite by default, PostgreSQL via DATABASE_URL on AWS).
Vanilla frontend served from ./static. Passwords: PBKDF2 (stdlib). Sessions: server-side tokens in a cookie.
"""
import hashlib, hmac, os, secrets, shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import (create_engine, Column, Integer, String, Text, Boolean,
                        DateTime, ForeignKey, UniqueConstraint)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

BASE_DIR = Path(__file__).parent
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./remora.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

PAID_PLANS = {"subscription_monthly", "subscription_yearly", "lifetime"}
FREE_BOOK_LIMIT = 1

# ---------- Models ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    plan = Column(String(40), default="free", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class SessionToken(Base):
    __tablename__ = "sessions"
    token = Column(String(128), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    type = Column(String(40), default="Memoir")  # Memoir | Legacy Book | Chronicle | Testament | Photo Story (free text, no validation list)
    description = Column(Text, default="")
    visibility = Column(String(20), default="private")  # private | family | public | testament
    family_emails = Column(Text, default="")  # comma-separated
    testament_recipients = Column(Text, default="")
    release_note = Column(Text, default="")
    publisher_optin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Chapter(Base):
    __tablename__ = "chapters"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, default="")
    visibility = Column(String(20), default="inherit")  # inherit | private | family | public | testament
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Media(Base):
    __tablename__ = "media"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True)
    kind = Column(String(20), default="photo")  # photo | audio | voice_transcript
    filename = Column(String(255), default="")  # stored file name (photo/audio); empty for transcript
    original_name = Column(String(255), default="")
    transcript = Column(Text, default="")  # for voice_transcript entries
    created_at = Column(DateTime, default=datetime.utcnow)

class TimelineEntry(Base):
    __tablename__ = "timeline_entries"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    date_text = Column(String(120), default="")
    event_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Letter(Base):
    __tablename__ = "letters"
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    recipient_name = Column(String(255), nullable=False)
    body = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("book_id", "user_id", name="uq_one_vote_per_user_book"),)
    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ---------- Helpers ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hexdk = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return hmac.compare_digest(dk.hex(), hexdk)
    except Exception:
        return False

def current_user(request: Request, db: Session):
    token = request.cookies.get("remora_session")
    if not token:
        return None
    s = db.query(SessionToken).filter_by(token=token).first()
    if not s:
        return None
    return db.query(User).filter_by(id=s.user_id).first()

def require_user(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        raise HTTPException(401, "Sign in required")
    return u

def user_json(u: User):
    return {"id": u.id, "name": u.name, "email": u.email, "plan": u.plan, "is_paid": u.plan in PAID_PLANS}

def vote_count(db: Session, book_id: int) -> int:
    return db.query(Vote).filter_by(book_id=book_id).count()

def book_json(db: Session, b: Book, include_owner=False):
    data = {"id": b.id, "owner_id": b.owner_id, "title": b.title, "type": b.type,
            "description": b.description or "", "visibility": b.visibility,
            "family_emails": b.family_emails or "", "testament_recipients": b.testament_recipients or "",
            "release_note": b.release_note or "", "publisher_optin": bool(b.publisher_optin),
            "votes": vote_count(db, b.id),
            "created_at": b.created_at.isoformat() if b.created_at else None}
    if include_owner:
        owner = db.query(User).filter_by(id=b.owner_id).first()
        data["author_name"] = owner.name if owner else ""
    return data

def get_own_book(db: Session, book_id: int, user: User) -> Book:
    b = db.query(Book).filter_by(id=book_id, owner_id=user.id).first()
    if not b:
        raise HTTPException(404, "Book not found")
    return b

def can_read_book(db: Session, b: Book, user) -> bool:
    if user and b.owner_id == user.id:
        return True
    if b.visibility == "public":
        return True
    if b.visibility == "family" and user:
        emails = [e.strip().lower() for e in (b.family_emails or "").split(",") if e.strip()]
        return user.email.lower() in emails
    return False  # private and testament are owner-only until a future verified release process

app = FastAPI(title="Remora")

# ---------- Auth ----------
@app.post("/api/signup")
async def signup(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name or not email or len(password) < 6:
        raise HTTPException(400, "Name, email and a password of 6+ characters are required")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(400, "An account with that email already exists")
    u = User(name=name, email=email, password_hash=hash_password(password), plan="free")
    db.add(u); db.commit(); db.refresh(u)
    return set_session(db, u)

@app.post("/api/signin")
async def signin(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    u = db.query(User).filter_by(email=email).first()
    if not u or not verify_password(data.get("password") or "", u.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return set_session(db, u)

def set_session(db: Session, u: User):
    token = secrets.token_urlsafe(48)
    db.add(SessionToken(token=token, user_id=u.id)); db.commit()
    resp = JSONResponse(user_json(u))
    resp.set_cookie("remora_session", token, httponly=True, samesite="lax", max_age=60*60*24*30)
    return resp

@app.post("/api/signout")
def signout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("remora_session")
    if token:
        db.query(SessionToken).filter_by(token=token).delete(); db.commit()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("remora_session")
    return resp

@app.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    return user_json(u) if u else JSONResponse({"user": None}, status_code=200) if False else (user_json(u) if u else {"id": None})

# ---------- Books ----------
@app.get("/api/books")
def my_books(db: Session = Depends(get_db), user: User = Depends(require_user)):
    books = db.query(Book).filter_by(owner_id=user.id).order_by(Book.created_at.desc()).all()
    return [book_json(db, b) for b in books]

@app.post("/api/books")
async def create_book(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    if user.plan not in PAID_PLANS:
        count = db.query(Book).filter_by(owner_id=user.id).count()
        if count >= FREE_BOOK_LIMIT:
            raise HTTPException(402, {"error": "Free plan allows 1 book. Upgrade to create more books.", "upgrade_required": True})
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    b = Book(owner_id=user.id, title=title, type=data.get("type") or "Memoir",
             description=data.get("description") or "")
    db.add(b); db.commit(); db.refresh(b)
    return book_json(db, b)

@app.put("/api/books/{book_id}")
async def update_book(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    new_visibility = data.get("visibility", b.visibility)
    if new_visibility == "testament" and user.plan not in PAID_PLANS:
        raise HTTPException(402, {"error": "Testament setup is a paid-plan feature. Upgrade to use it.", "upgrade_required": True})
    for field in ("title", "type", "description", "visibility", "family_emails", "testament_recipients", "release_note"):
        if field in data:
            setattr(b, field, data[field])
    if "publisher_optin" in data:
        b.publisher_optin = bool(data["publisher_optin"])
    db.commit(); db.refresh(b)
    return book_json(db, b)

@app.delete("/api/books/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    for model in (Chapter, Media, TimelineEntry, Letter, Vote):
        db.query(model).filter_by(book_id=b.id).delete()
    db.delete(b); db.commit()
    return {"ok": True}

@app.get("/api/books/{book_id}")
def read_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    b = db.query(Book).filter_by(id=book_id).first()
    user = current_user(request, db)
    if not b or not can_read_book(db, b, user):
        raise HTTPException(404, "Book not found or not shared with you")
    chapters = db.query(Chapter).filter_by(book_id=b.id).order_by(Chapter.sort_order, Chapter.id).all()
    # Non-owners only see chapters that are inherit/public (owner sees all)
    if not (user and user.id == b.owner_id):
        chapters = [c for c in chapters if c.visibility in ("inherit", "public")]
    media = db.query(Media).filter_by(book_id=b.id).all()
    timeline = db.query(TimelineEntry).filter_by(book_id=b.id).order_by(TimelineEntry.id).all()
    letters = db.query(Letter).filter_by(book_id=b.id).all() if (user and user.id == b.owner_id) else []
    data = book_json(db, b, include_owner=True)
    data["chapters"] = [{"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility} for c in chapters]
    data["media"] = [{"id": m.id, "chapter_id": m.chapter_id, "kind": m.kind,
                      "url": f"/uploads/{m.filename}" if m.filename else None,
                      "original_name": m.original_name, "transcript": m.transcript or ""} for m in media]
    data["timeline"] = [{"id": t.id, "date_text": t.date_text, "event_text": t.event_text} for t in timeline]
    data["letters"] = [{"id": l.id, "recipient_name": l.recipient_name, "body": l.body} for l in letters]
    data["my_vote"] = bool(user and db.query(Vote).filter_by(book_id=b.id, user_id=user.id).first())
    return data

# ---------- Chapters ----------
@app.post("/api/books/{book_id}/chapters")
async def create_chapter(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    c = Chapter(book_id=b.id, title=(data.get("title") or "Untitled chapter").strip(),
                body=data.get("body") or "", visibility=data.get("visibility") or "inherit",
                sort_order=db.query(Chapter).filter_by(book_id=b.id).count())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility}

@app.put("/api/chapters/{chapter_id}")
async def update_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.query(Chapter).filter_by(id=chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    get_own_book(db, c.book_id, user)
    data = await request.json()
    for field in ("title", "body", "visibility"):
        if field in data:
            setattr(c, field, data[field])
    db.commit()
    return {"id": c.id, "title": c.title, "body": c.body, "visibility": c.visibility}

@app.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.query(Chapter).filter_by(id=chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    get_own_book(db, c.book_id, user)
    db.query(Media).filter_by(chapter_id=c.id).update({"chapter_id": None})
    db.delete(c); db.commit()
    return {"ok": True}

# ---------- Media / timeline / letters ----------
@app.post("/api/books/{book_id}/media")
async def upload_media(book_id: int, kind: str = Form("photo"), chapter_id: str = Form(""),
                       transcript: str = Form(""), file: UploadFile = File(None),
                       db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    cid = int(chapter_id) if chapter_id.strip().isdigit() else None
    if kind == "voice_transcript":
        m = Media(book_id=b.id, chapter_id=cid, kind=kind, transcript=transcript)
    else:
        if file is None:
            raise HTTPException(400, "A file is required for photo/audio uploads")
        safe = f"{b.id}_{secrets.token_hex(6)}_{Path(file.filename or 'file').name}"
        dest = UPLOAD_DIR / safe
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        m = Media(book_id=b.id, chapter_id=cid, kind=kind, filename=safe, original_name=file.filename or safe)
    db.add(m); db.commit(); db.refresh(m)
    return {"id": m.id, "kind": m.kind, "url": f"/uploads/{m.filename}" if m.filename else None, "transcript": m.transcript or ""}

@app.post("/api/books/{book_id}/timeline")
async def add_timeline(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    t = TimelineEntry(book_id=b.id, date_text=data.get("date_text") or "", event_text=(data.get("event_text") or "").strip())
    if not t.event_text:
        raise HTTPException(400, "Event text is required")
    db.add(t); db.commit(); db.refresh(t)
    return {"id": t.id, "date_text": t.date_text, "event_text": t.event_text}

@app.post("/api/books/{book_id}/letters")
async def add_letter(book_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = get_own_book(db, book_id, user)
    data = await request.json()
    l = Letter(book_id=b.id, recipient_name=(data.get("recipient_name") or "").strip(), body=data.get("body") or "")
    if not l.recipient_name:
        raise HTTPException(400, "Recipient name is required")
    db.add(l); db.commit(); db.refresh(l)
    return {"id": l.id, "recipient_name": l.recipient_name, "body": l.body}

# ---------- Discover / voting / publishers ----------
@app.get("/api/discover")
def discover(db: Session = Depends(get_db), sort: str = "votes"):
    books = db.query(Book).filter_by(visibility="public").all()
    out = [book_json(db, b, include_owner=True) for b in books]
    out.sort(key=lambda x: x["votes"], reverse=True) if sort == "votes" else out.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return out

@app.get("/api/publishers")
def publishers(db: Session = Depends(get_db)):
    books = db.query(Book).filter_by(visibility="public", publisher_optin=True).all()
    out = [book_json(db, b, include_owner=True) for b in books]
    out.sort(key=lambda x: x["votes"], reverse=True)
    return out

@app.post("/api/books/{book_id}/vote")
def vote(book_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    b = db.query(Book).filter_by(id=book_id, visibility="public").first()
    if not b:
        raise HTTPException(404, "Public book not found")
    if db.query(Vote).filter_by(book_id=b.id, user_id=user.id).first():
        raise HTTPException(400, "You already voted for this book")
    db.add(Vote(book_id=b.id, user_id=user.id)); db.commit()
    return {"ok": True, "votes": vote_count(db, b.id)}

# ---------- Plans / simulated checkout ----------
PLANS = [
    {"id": "free", "name": "Free", "price": "$0", "features": ["1 book", "Chapters, timeline, letters, photo & voice uploads", "Private and Family sharing", "Read in app"]},
    {"id": "subscription_monthly", "name": "Keeper — Monthly", "price": "$9/month", "features": ["Unlimited books", "PDF export", "Testament setup & recipients", "Public stories + publisher opt-in", "Print ordering"]},
    {"id": "subscription_yearly", "name": "Keeper — Yearly", "price": "$79/year", "features": ["Everything in Monthly", "Two months free vs monthly"]},
    {"id": "lifetime", "name": "Lifetime Legacy — One-time", "price": "$249 once", "features": ["Everything in Keeper, forever", "No subscription — one payment"]},
]

@app.get("/api/plans")
def plans():
    return PLANS

@app.post("/api/checkout")
async def checkout(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await request.json()
    plan = data.get("plan")
    if plan not in [p["id"] for p in PLANS]:
        raise HTTPException(400, "Unknown plan")
    # SIMULATED checkout: no real payment is taken. Stripe replaces this endpoint at real launch (see README).
    user.plan = plan
    db.commit()
    return {"ok": True, "simulated": True, "user": user_json(user)}

# ---------- PDF export (paid gate) ----------
@app.get("/api/books/{book_id}/pdf")
def export_pdf(book_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "Sign in required")
    b = db.query(Book).filter_by(id=book_id).first()
    if not b or not can_read_book(db, b, user):
        raise HTTPException(404, "Book not found")
    if b.owner_id == user.id and user.plan not in PAID_PLANS:
        raise HTTPException(402, "PDF export is a paid-plan feature. Upgrade on the Pricing page.")
    from fpdf import FPDF
    def clean(s):
        return (s or "").encode("latin-1", "replace").decode("latin-1")
    def txt(pdf, size, style, h, s):
        pdf.set_font("helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, clean(s), new_x="LMARGIN", new_y="NEXT")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    txt(pdf, 24, "B", 12, b.title)
    txt(pdf, 12, "", 7, f"{b.type} - Remora")
    if b.description:
        pdf.ln(4); txt(pdf, 12, "", 7, b.description)
    chapters = db.query(Chapter).filter_by(book_id=b.id).order_by(Chapter.sort_order, Chapter.id).all()
    for c in chapters:
        pdf.add_page()
        txt(pdf, 18, "B", 10, c.title)
        txt(pdf, 12, "", 7, c.body or "")
    timeline = db.query(TimelineEntry).filter_by(book_id=b.id).all()
    if timeline:
        pdf.add_page(); txt(pdf, 18, "B", 10, "Chronicle / Timeline")
        for t in timeline:
            txt(pdf, 12, "", 7, f"{t.date_text}: {t.event_text}")
    out = bytes(pdf.output())
    return Response(content=out, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="remora-book-{b.id}.pdf"'})

# ---------- Static frontend ----------
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "app": "remora"}
