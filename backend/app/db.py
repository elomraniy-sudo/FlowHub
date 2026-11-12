"""SQLAlchemy models. One generic `Asset` table so scripts / apps can be added later
alongside n8n workflows (the `kind` column + the analyzer registry are the extension points)."""
import json
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    kind = Column(String(32), default="n8n_workflow", index=True)  # n8n_workflow | script | webapp ...
    name = Column(String(255), nullable=False)
    owner = Column(String(255), default="")
    source = Column(String(32), default="upload")       # upload | drive | n8n
    source_ref = Column(String(512), default="")         # drive file id, n8n workflow id, filename
    content_hash = Column(String(64), index=True)
    raw = Column(Text)                                   # original n8n JSON (string)

    # deterministic extraction
    nodes = Column(JSON, default=list)                   # [{name,type,credentials:[...]}]
    integrations = Column(JSON, default=list)            # ["slack","googleSheets",...]
    trigger_type = Column(String(64), default="manual")  # webhook | schedule | manual | app-event
    credentials_required = Column(JSON, default=list)    # [{node,type,name}]

    # LLM enrichment
    summary = Column(Text, default="")
    category = Column(String(128), default="Uncategorized", index=True)
    tags = Column(JSON, default=list)
    use_cases = Column(JSON, default=list)
    inputs = Column(JSON, default=list)                  # [{name, where(node), description}]
    outputs = Column(JSON, default=list)
    customizable = Column(JSON, default=list)            # [{key,label,node,path,kind,description}]
    analysis_status = Column(String(32), default="pending")  # pending | done | failed

    # registry written by the MAIN AI n8n workflow (sheet "All N8N Flows" + "AI DOC" folder)
    n8n_workflow_id = Column(String(64), default="")      # sheet "Flow ID"
    sheet_description = Column(Text, default="")          # sheet "Small Description"
    doc_link = Column(String(512), default="")            # sheet "Doc Link"
    doc_text = Column(Text, default="")                   # plain text of that Google Doc
    in_registry = Column(Integer, default=0)              # 1 = present in the sheet

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, include_raw: bool = False) -> dict:
        d = {
            "id": self.id, "kind": self.kind, "name": self.name, "owner": self.owner,
            "source": self.source, "source_ref": self.source_ref,
            "nodes": self.nodes, "integrations": self.integrations, "trigger_type": self.trigger_type,
            "credentials_required": self.credentials_required,
            "summary": self.summary, "category": self.category, "tags": self.tags,
            "use_cases": self.use_cases, "inputs": self.inputs, "outputs": self.outputs,
            "customizable": self.customizable, "analysis_status": self.analysis_status,
            "n8n_workflow_id": self.n8n_workflow_id, "sheet_description": self.sheet_description,
            "doc_link": self.doc_link, "has_doc": bool(self.doc_text), "in_registry": bool(self.in_registry),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_raw:
            d["raw"] = json.loads(self.raw) if self.raw else None
            d["doc_text"] = self.doc_text
        return d


class RunLog(Base):
    __tablename__ = "run_logs"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, index=True)
    action = Column(String(64))       # deploy | activate | trigger | drive_upload
    user = Column(String(255), default="")
    detail = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(engine)
    # poor man's migration: add columns introduced after the DB was first created
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns("assets")}
    with engine.begin() as conn:
        for col in Asset.__table__.columns:
            if col.name not in existing:
                conn.execute(text(f'ALTER TABLE assets ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
