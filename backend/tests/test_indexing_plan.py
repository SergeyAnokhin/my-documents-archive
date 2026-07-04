from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AIProvider, Document
from app.services.indexing_plan import build_index_plan
from app.services.provider_capabilities import provider_capabilities


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plan.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_lazy_plan_reuses_text_and_skips_completed_analysis(tmp_path):
    db = _session(tmp_path)
    db.add_all([
        Document(filename="ready.txt", filepath="ready.txt", ocr_text="existing", ocr_status="done", analysis_status="done"),
        Document(filename="text.pdf", filepath="text.pdf", ocr_text="existing", ocr_status="done", analysis_status="pending"),
        Document(filename="native.docx", filepath="native.docx", analysis_status="pending"),
        Document(filename="scan.pdf", filepath="scan.pdf", analysis_status="pending"),
    ])
    db.commit()

    plan = build_index_plan(db, "mistral_gemini")

    assert plan["total_candidates"] == 3
    assert plan["already_complete"] == 1
    assert plan["already_has_text"] == 1
    assert plan["native_text"] == 1
    assert plan["mistral_ocr"] == 1
    assert plan["gemini_text"] == 3
    assert plan["gemini_vision"] == 0


def test_gemini_complete_routes_existing_text_without_image(tmp_path):
    db = _session(tmp_path)
    db.add_all([
        Document(filename="text.pdf", filepath="text.pdf", ocr_text="existing", analysis_status="pending"),
        Document(filename="scan.jpg", filepath="scan.jpg", analysis_status="pending"),
    ])
    db.commit()
    plan = build_index_plan(db, "gemini_complete")
    assert plan["gemini_text"] == 1
    assert plan["gemini_vision"] == 1


def test_capability_overrides_win_over_model_inference():
    provider = AIProvider(
        name="Gemini", provider_type="gemini", api_key="x",
        model="gemini-2.5-flash", extra_params={"capabilities": {"vision": False}},
    )
    capabilities = provider_capabilities(provider)
    assert capabilities["analysis"] is True
    assert capabilities["vision"] is False
