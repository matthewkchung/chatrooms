import os
import random
from datetime import datetime, timezone

from flask import Flask, abort, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.orm import selectinload

app = Flask(__name__)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable is required.")

# Some platforms still provide the deprecated postgres:// prefix.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "development-only-secret-key")

db = SQLAlchemy(app)
migrate = Migrate(app, db)


ADJECTIVES = [
    "Blue",
    "Red",
    "Green",
    "Silver",
    "Golden",
    "Quiet",
    "Happy",
    "Brave",
    "Swift",
    "Gentle",
    "Clever",
    "Calm",
    "Bright",
    "Lucky",
    "Misty",
    "Sunny",
    "Cool",
    "Wild",
    "Cosmic",
    "Tiny",
]

ANIMALS = [
    "Fox",
    "Wolf",
    "Bear",
    "Otter",
    "Panda",
    "Tiger",
    "Lion",
    "Koala",
    "Rabbit",
    "Falcon",
    "Hawk",
    "Raven",
    "Badger",
    "Moose",
    "Gecko",
    "Lynx",
    "Bison",
    "Whale",
    "Dolphin",
    "Owl",
]


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    messages = db.relationship(
        "Message",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(
        db.Integer,
        db.ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=False)
    posted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    room = db.relationship("Room", back_populates="messages")


def generate_nickname():
    adjective = random.choice(ADJECTIVES)
    animal = random.choice(ANIMALS)
    number = random.randint(10, 99)
    return f"{adjective}{animal}{number}"


@app.before_request
def assign_anonymous_nickname():
    if "nickname" not in session:
        session["nickname"] = generate_nickname()


@app.template_filter("datetime")
def format_datetime(value):
    if value is None:
        return "No activity yet"

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        room_name = request.form.get("name", "").strip()

        if not room_name:
            return redirect(url_for("home"))

        if len(room_name) > 120:
            room_name = room_name[:120]

        room = Room(
            name=room_name,
            created_by=session["nickname"],
        )
        db.session.add(room)
        db.session.commit()

        return redirect(url_for("room", room_id=room.id))

    message_count = func.count(Message.id).label("message_count")
    last_activity = func.max(Message.posted_at).label("last_activity")

    rooms = (
        db.session.query(
            Room,
            message_count,
            last_activity,
        )
        .outerjoin(Message, Room.id == Message.room_id)
        .group_by(Room.id)
        .order_by(
            func.coalesce(last_activity, Room.created_at).desc(),
            Room.id.desc(),
        )
        .all()
    )

    return render_template(
        "home.html",
        rooms=rooms,
        nickname=session["nickname"],
    )


@app.route("/rooms/<int:room_id>", methods=["GET", "POST"])
def room(room_id):
    chat_room = db.session.get(Room, room_id)

    if chat_room is None:
        abort(404)

    if request.method == "POST":
        content = request.form.get("content", "").strip()

        if content:
            # Keep individual messages reasonably bounded.
            content = content[:4000]

            message = Message(
                room_id=chat_room.id,
                author=session["nickname"],
                content=content,
            )
            db.session.add(message)
            db.session.commit()

        # POST/Redirect/GET prevents duplicate messages when the browser refreshes.
        return redirect(url_for("room", room_id=chat_room.id))

    newest_messages = (
        Message.query
        .filter_by(room_id=chat_room.id)
        .order_by(Message.posted_at.desc(), Message.id.desc())
        .limit(50)
        .all()
    )

    messages = list(reversed(newest_messages))

    return render_template(
        "room.html",
        room=chat_room,
        messages=messages,
        nickname=session["nickname"],
    )


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "404.html",
        nickname=session.get("nickname", "Anonymous"),
    ), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
