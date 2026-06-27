"""Suggest Lucide icon names for custom document types via LLM.

Custom types (not in the built-in AI taxonomy) get a default FileText icon
on the frontend. This service batch-assigns better icons on demand.

Call suggest_icons_for_types() with a list of type slugs and a DB session;
it calls the LLM once per type, detects icon conflicts, retries up to
max_retries=5 per type, and persists the results in AppSettings.
"""
import json
import logging
from typing import Optional

from sqlalchemy import distinct as sa_distinct
from sqlalchemy.orm import Session

from .ai_analysis import _get_providers, run_text
from .ai_common import strip_code_fences
from ..models import AppSettings, Document

log = logging.getLogger(__name__)

SETTINGS_KEY = "custom_type_icons"

# Slugs from DOCUMENT_TYPES_BLOCK — types not in this set are "custom".
BUILT_IN_TYPE_SLUGS: frozenset[str] = frozenset({
    "passport", "national_id", "driver_license", "birth_certificate",
    "death_certificate", "marriage_certificate", "divorce_certificate",
    "residence_permit", "visa", "contract", "agreement", "power_of_attorney",
    "court_document", "invoice", "bank_statement", "receipt", "tax_document",
    "payslip", "property_deed", "title_certificate", "insurance_policy",
    "medical_certificate", "prescription", "medical_record", "diploma",
    "certificate", "transcript", "student_id", "permit", "license",
    "registration", "notarial_deed", "letter", "notice", "announcement",
    "photo", "scan", "unclassified",
})

# Icons already assigned to built-in types — must mirror typeIcons.ts TYPE_ICONS values.
STATIC_ICON_VALUES: frozenset[str] = frozenset({
    "BookUser", "IdCard", "Car", "Baby", "Cross", "Heart", "HeartCrack",
    "House", "Plane", "FileSignature", "Handshake", "UserCheck", "Gavel",
    "ReceiptText", "Landmark", "Receipt", "Coins", "Wallet", "KeyRound",
    "BadgeCheck", "Umbrella", "Stethoscope", "Pill", "ClipboardPlus",
    "GraduationCap", "Award", "ClipboardList", "School", "FileCheck",
    "FileBadge", "ClipboardCheck", "Stamp", "Mail", "Bell", "Megaphone",
    "Image", "ScanLine", "FileQuestion",
})

# All Lucide icon names the LLM may choose from.
# Includes both static icons (as context examples) and the extra pool for custom types.
ALLOWED_ICONS: tuple[str, ...] = (
    # Built-in icons — referenced as context; excluded from custom assignments
    "Award", "Baby", "BadgeCheck", "Bell", "BookUser",
    "Car", "ClipboardCheck", "ClipboardList", "ClipboardPlus", "Coins",
    "Cross", "FileBadge", "FileCheck", "FileQuestion", "FileSignature", "FileText",
    "GraduationCap", "Gavel", "Handshake", "Heart", "HeartCrack", "House",
    "IdCard", "Image", "KeyRound", "Landmark", "Mail", "Megaphone",
    "Pill", "Plane", "Receipt", "ReceiptText", "ScanLine", "School",
    "Stamp", "Stethoscope", "Umbrella", "UserCheck", "Wallet",
    # Extra pool available for custom types
    "Archive", "Banknote", "BookOpen", "Briefcase", "Building", "Building2",
    "CalendarDays", "Clock", "CreditCard", "Flag", "FolderOpen", "Globe",
    "Lock", "MapPin", "Newspaper", "Package", "Phone", "Printer",
    "Scale", "Shield", "ShieldCheck", "ShoppingBag", "Tag", "Truck", "Users",
)

_SUGGEST_SYSTEM = """\
You are a UI icon assignment assistant for a document management application.
Given a document type slug, suggest the single most appropriate Lucide icon name.

Rules:
- Return ONLY a JSON object: {"icon": "IconName"}
- IconName must be from the AVAILABLE list (exact PascalCase spelling)
- Do NOT suggest any icon from the EXCLUDED list — those are already assigned to other types
- Choose based on the document type's meaning, not just keyword similarity
- If nothing fits perfectly, pick the closest metaphor"""


async def suggest_icons_for_types(
    type_slugs: list[str],
    db: Session,
) -> dict[str, str]:
    """Assign Lucide icons to a batch of custom type slugs.

    Skips slugs already in custom_type_icons. Builds up the taken-icons set
    as it goes so no two types receive the same icon. Persists new assignments
    to AppSettings before returning.

    Returns only the newly assigned {type_slug: icon_name} pairs.
    """
    if not type_slugs:
        return {}

    providers = _get_providers(db)
    if not providers:
        log.warning("No AI providers configured; cannot suggest icons")
        return {}

    existing = get_custom_type_icons(db)
    taken = set(STATIC_ICON_VALUES) | set(existing.values())

    newly_assigned: dict[str, str] = {}

    for slug in type_slugs:
        if slug in existing:
            continue
        icon = await _suggest_one(slug, taken, providers)
        if icon:
            newly_assigned[slug] = icon
            taken.add(icon)

    if newly_assigned:
        _save_custom_type_icons({**existing, **newly_assigned}, db)

    return newly_assigned


async def _suggest_one(
    type_slug: str,
    taken: set[str],
    providers: list,
    max_retries: int = 5,
) -> Optional[str]:
    """Ask LLM for one icon; retry when the result conflicts or is invalid."""
    excluded = set(taken)

    for attempt in range(max_retries):
        available = [ic for ic in ALLOWED_ICONS if ic not in excluded]
        if not available:
            log.warning("No icons left for '%s' after %d exclusions", type_slug, len(excluded))
            return None

        user_msg = (
            f"Document type: {type_slug}\n\n"
            f"AVAILABLE: {', '.join(available)}\n"
            f"EXCLUDED (already in use): {', '.join(sorted(excluded))}"
        )

        for provider in providers:
            try:
                raw, _, _, _ = await run_text(provider, _SUGGEST_SYSTEM, user_msg)
                data = json.loads(strip_code_fences(raw))
                icon = str(data.get("icon", "")).strip()

                if icon not in ALLOWED_ICONS:
                    log.debug("Unknown icon '%s' for '%s' (attempt %d)", icon, type_slug, attempt)
                    excluded.add(icon)
                    break  # retry outer loop

                if icon in excluded:
                    log.debug("Conflicting icon '%s' for '%s' (attempt %d)", icon, type_slug, attempt)
                    excluded.add(icon)
                    break  # retry outer loop

                return icon

            except Exception as e:
                log.warning("Icon provider '%s' failed: %s", provider.name, e)

    log.warning("Exhausted %d retries for type '%s'", max_retries, type_slug)
    return None


def get_custom_type_icons(db: Session) -> dict[str, str]:
    """Load the custom type → Lucide icon name map from AppSettings."""
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_custom_type_icons(icons: dict[str, str], db: Session) -> None:
    """Persist custom type → icon map to AppSettings (upsert)."""
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    value = json.dumps(icons, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=value))
    db.commit()


def get_pending_custom_types(db: Session) -> list[str]:
    """Return distinct custom type slugs in the library that have no icon yet."""
    existing = get_custom_type_icons(db)
    rows = (
        db.query(sa_distinct(Document.document_type))
        .filter(Document.document_type.isnot(None))
        .all()
    )
    all_types = {row[0] for row in rows if row[0]}
    custom = all_types - BUILT_IN_TYPE_SLUGS
    return sorted(t for t in custom if t not in existing)
