"""Database tables, defined with SQLAlchemy so they work on SQLite and PostgreSQL.

Table and column names match the original SQLite schema, so an existing
instance/food_waste.sqlite3 file keeps working without a data migration.
Times are stored as ISO 8601 UTC text, such as 2026-10-01T07:00:00Z, which
sorts correctly as text on every database. The app sets created_at and
updated_at itself, so no database-specific time functions are needed.
"""

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# 64-bit ids on PostgreSQL. SQLite needs plain INTEGER for its auto-numbered ids.
Id = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="user_name_not_blank"),
        CheckConstraint("length(trim(username)) > 0", name="username_not_blank"),
        CheckConstraint("role IN ('entry', 'manager', 'admin')", name="user_role_valid"),
        CheckConstraint("active IN (0, 1)", name="user_active_flag"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class _Lookup:
    """Shared columns for the areas, categories and reasons lists."""

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class AreaRow(_Lookup, Base):
    __tablename__ = "areas"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="area_name_not_blank"),)


class CategoryRow(_Lookup, Base):
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="category_name_not_blank"),)


class ReasonRow(_Lookup, Base):
    __tablename__ = "reasons"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="reason_name_not_blank"),)


LOOKUP_TABLES = {"areas": AreaRow, "categories": CategoryRow, "reasons": ReasonRow}


class WasteRecordRow(Base):
    __tablename__ = "waste_records"
    __table_args__ = (
        CheckConstraint("length(trim(event_at)) > 0", name="event_at_not_blank"),
        CheckConstraint("quantity_kg > 0", name="quantity_positive"),
        Index("idx_waste_records_event_at", "event_at"),
        Index("idx_waste_records_area_id", "area_id"),
        Index("idx_waste_records_category_id", "category_id"),
        Index("idx_waste_records_reason_id", "reason_id"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    event_at: Mapped[str] = mapped_column(String(32), nullable=False)
    area_id: Mapped[int] = mapped_column(Id, ForeignKey("areas.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(Id, ForeignKey("categories.id"), nullable=False)
    reason_id: Mapped[int] = mapped_column(Id, ForeignKey("reasons.id"), nullable=False)
    quantity_kg: Mapped[float] = mapped_column(Float, nullable=False)
    user_id: Mapped[int] = mapped_column(Id, ForeignKey("users.id"), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class MealCheckRow(Base):
    """One buffet meal counted from photos: pieces at the start and at the end of the meal.

    The kilograms left over become a waste record; what was eaten feeds the meal forecast.
    """

    __tablename__ = "meal_checks"
    __table_args__ = (
        CheckConstraint("start_count >= 0 AND end_count >= 0 AND short_count >= 0", name="meal_check_counts"),
        CheckConstraint("end_count <= start_count", name="meal_check_end_not_above_start"),
        CheckConstraint("kg_per_piece > 0", name="meal_check_piece_weight_positive"),
        CheckConstraint("guest_count > 0", name="meal_check_guests_positive"),
        Index("idx_meal_checks_event_at", "event_at"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    event_at: Mapped[str] = mapped_column(String(32), nullable=False)
    meal_type: Mapped[str] = mapped_column(Text, nullable=False)
    food_item: Mapped[str] = mapped_column(Text, nullable=False)
    count_label: Mapped[str] = mapped_column(Text, nullable=False)
    start_count: Mapped[int] = mapped_column(Integer, nullable=False)
    end_count: Mapped[int] = mapped_column(Integer, nullable=False)
    short_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    kg_per_piece: Mapped[float] = mapped_column(Float, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    area_id: Mapped[int] = mapped_column(Id, ForeignKey("areas.id"), nullable=False)
    waste_record_id: Mapped[int | None] = mapped_column(Id, ForeignKey("waste_records.id"), nullable=True)
    shortage_record_id: Mapped[int | None] = mapped_column(Id, ForeignKey("waste_records.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(Id, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


# ---- Automatic camera capture ---------------------------------------------------------------

class CaptureRow(Base):
    """One photo taken by a buffet camera (or a failed attempt), and how far its counting got.

    Every photo is kept on disk and here, so they can later become a labelled training dataset.
    """

    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint("kind IN ('start', 'end')", name="capture_kind_valid"),
        CheckConstraint("status IN ('ok', 'failed')", name="capture_status_valid"),
        CheckConstraint("count_status IN ('pending', 'counted', 'failed', 'needs_setup', 'not_counted')",
                        name="capture_count_status_valid"),
        Index("idx_captures_day_meal", "capture_date", "meal_type", "kind"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    captured_at: Mapped[str] = mapped_column(String(32), nullable=False)       # UTC, like every other time
    capture_date: Mapped[str] = mapped_column(String(10), nullable=False)      # local (Sri Lanka) date
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)         # breakfast, lunch, dinner
    kind: Mapped[str] = mapped_column(String(5), nullable=False)               # start or end
    station: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)  # inside the captures folder
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    count_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    count_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    counted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class CaptureCountRow(Base):
    """How many of one food the model found in one photo. A zero is stored too."""

    __tablename__ = "capture_counts"
    __table_args__ = (
        CheckConstraint("count >= 0", name="capture_count_not_negative"),
        Index("idx_capture_counts_capture_id", "capture_id"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    capture_id: Mapped[int] = mapped_column(Id, ForeignKey("captures.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)             # what was counted, e.g. "egg"
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)  # percent, e.g. 30
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    detections: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")  # boxes and scores, JSON
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class CameraFoodRow(Base):
    """A food the cameras look for, with its weight per piece.

    station empty means every station; rows for a named station replace that list for the station.
    """

    __tablename__ = "camera_foods"
    __table_args__ = (
        CheckConstraint("kg_per_piece > 0", name="camera_food_weight_positive"),
        CheckConstraint("active IN (0, 1)", name="camera_food_active_flag"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    station: Mapped[str | None] = mapped_column(String(40), nullable=True)
    count_label: Mapped[str] = mapped_column(String(40), nullable=False)       # what the model looks for
    dish: Mapped[str | None] = mapped_column(Text, nullable=True)              # the menu dish it belongs to
    kg_per_piece: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class MealCheckDraftRow(Base):
    """A meal whose start and end photos are both counted, waiting for staff to add the guests and confirm.

    The counts are read live from the photos until it is confirmed; then what staff saved is kept in details.
    """

    __tablename__ = "meal_check_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('waiting', 'confirmed')", name="meal_check_draft_status_valid"),
        UniqueConstraint("capture_date", "meal_type", "station", name="meal_check_draft_one_per_meal"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    capture_date: Mapped[str] = mapped_column(String(10), nullable=False)
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    station: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="waiting")
    details: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")      # JSON, once confirmed
    meal_check_ids: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
