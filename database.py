from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import text
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./checks.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    checks = relationship("CheckRecord", back_populates="user")

class CheckRecord(Base):
    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_full_name = Column(String, nullable=True)
    account_no = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    pay_to_the_order_of = Column(String, nullable=True)
    check_no = Column(String, nullable=True)
    amount = Column(String, nullable=True)
    bank_name = Column(String, nullable=True)
    date = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    is_received = Column(Boolean, default=False)
    received_date = Column(String, nullable=True)
    cr = Column(String, nullable=True)
    cr_date = Column(String, nullable=True)
    date_deposited = Column(String, nullable=True)      # Date when deposited
    bank_deposited = Column(String, nullable=True)      # Bank where deposited
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="checks")

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

# Migrations for existing tables
inspector = inspect(engine)
if 'checks' in inspector.get_table_names():
    columns = [col['name'] for col in inspector.get_columns('checks')]
    with engine.connect() as conn:
        # Rename delivery_date to date_deposited if it exists
        if 'delivery_date' in columns:
            conn.execute(text("ALTER TABLE checks RENAME COLUMN delivery_date TO date_deposited"))
            conn.commit()
            print("Renamed delivery_date to date_deposited")
            # Refresh columns list
            columns = [col['name'] for col in inspector.get_columns('checks')]
        # Add date_deposited if still missing
        if 'date_deposited' not in columns:
            conn.execute(text("ALTER TABLE checks ADD COLUMN date_deposited TEXT"))
            conn.commit()
            print("Added date_deposited column")
        # Add bank_deposited if missing
        if 'bank_deposited' not in columns:
            conn.execute(text("ALTER TABLE checks ADD COLUMN bank_deposited TEXT"))
            conn.commit()
            print("Added bank_deposited column")