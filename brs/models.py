from datetime import datetime
from sqlalchemy import create_engine, String, Integer, LargeBinary, Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship, foreign
from .config import DATABASE_URL

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="user")

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(foreign(User.id), nullable=False)

    club_slug: Mapped[str] = mapped_column(String(64))
    course_id: Mapped[str] = mapped_column(String(16))

    member_username_enc: Mapped[bytes] = mapped_column(LargeBinary)
    member_password_enc: Mapped[bytes] = mapped_column(LargeBinary)

    target_date: Mapped[str] = mapped_column(String(10))  # YYYY/MM/DD
    earliest: Mapped[str] = mapped_column(String(5))      # HH:MM
    latest: Mapped[str] = mapped_column(String(5))        # HH:MM
    current_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    required_seats: Mapped[int] = mapped_column(Integer, default=4)
    accept_at_least: Mapped[bool] = mapped_column(Boolean, default=True)
    player_ids_csv: Mapped[str] = mapped_column(String(255))

    poll_seconds: Mapped[int] = mapped_column(Integer, default=20)
    max_minutes: Mapped[int] = mapped_column(Integer, default=120)

    status: Mapped[str] = mapped_column(String(20), default="active")  # active, running, success, failed, expired, stopped
    last_log: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="jobs")

    def player_ids(self) -> list[int]:
        return [int(x.strip()) for x in self.player_ids_csv.split(",") if x.strip()]

class Club(Base):
    __tablename__ = "clubs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    country: Mapped[str] = mapped_column(String(64), default="UK")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("slug", name="uq_club_slug"),)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def init_db():
    Base.metadata.create_all(engine)
