import json
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import moscow_now


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    referred_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=moscow_now)

    predictions: Mapped[list["Prediction"]] = relationship("Prediction", back_populates="user")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    team_a: Mapped[str] = mapped_column(String(64), nullable=False)
    team_b: Mapped[str] = mapped_column(String(64), nullable=False)
    _options: Mapped[str] = mapped_column("options", Text, nullable=False, default="[]")
    match_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Текстовое представление правильных ответов для отображения и обратной
    # совместимости со старыми матчами (несколько ответов разделяются " / ").
    correct_answer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # JSON-список правильных вариантов (источник истины для нескольких ответов).
    _correct_answers: Mapped[str | None] = mapped_column("correct_answers", Text, nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    predictions: Mapped[list["Prediction"]] = relationship("Prediction", back_populates="match")

    @property
    def options(self) -> list[str]:
        return json.loads(self._options)

    @options.setter
    def options(self, value: list[str]) -> None:
        self._options = json.dumps(value, ensure_ascii=False)

    @property
    def correct_answers(self) -> list[str]:
        if self._correct_answers:
            return json.loads(self._correct_answers)
        # Обратная совместимость: матч завершён до поддержки нескольких ответов.
        if self.correct_answer:
            return [self.correct_answer]
        return []

    @correct_answers.setter
    def correct_answers(self, value: list[str]) -> None:
        self._correct_answers = json.dumps(value, ensure_ascii=False)
        self.correct_answer = " / ".join(value) if value else None


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_prediction_user_match"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    answer: Mapped[str] = mapped_column(String(128), nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=moscow_now)

    user: Mapped["User"] = relationship("User", back_populates="predictions")
    match: Mapped["Match"] = relationship("Match", back_populates="predictions")
