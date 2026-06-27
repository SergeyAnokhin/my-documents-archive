// Pins custom-icon resolution in typeIcons.ts.
// See docs/code-map.md: "components/documents/typeIcons.ts | Maps each document_type
// slug → a lucide icon; iconForType() with keyword + FileText fallbacks."
//
// Each test carries:
//   Doc:  which documented area it protects
//   Rule: the specific behavior it asserts
import { describe, it, expect, beforeEach } from "vitest";
import { FileText } from "lucide-react";
import { iconForType, setCustomTypeIcons, ICON_NAME_MAP } from "./typeIcons";

// Reset custom icons before each test so tests don't bleed into each other.
beforeEach(() => setCustomTypeIcons({}));

describe("iconForType — built-in types", () => {
  it("returns a built-in icon for a known taxonomy slug", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: TYPE_ICONS maps each taxonomy slug to a distinct component, not the FileText fallback.
    const icon = iconForType("invoice");
    expect(icon).not.toBe(FileText);
    expect(icon).not.toBeNull();
  });

  it("returns FileText for null / undefined type", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: null and undefined both fall through to the FileText default.
    expect(iconForType(null)).toBe(FileText);
    expect(iconForType(undefined)).toBe(FileText);
    expect(iconForType("")).toBe(FileText);
  });

  it("trims and lowercases before looking up", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: slug is normalised so "  Invoice  " resolves the same as "invoice".
    const normal = iconForType("invoice");
    const padded = iconForType("  Invoice  ");
    expect(padded).toBe(normal);
  });
});

describe("iconForType — keyword fallback", () => {
  it("matches a keyword in a free-form type slug", () => {
    // Doc:  code-map.md → typeIcons.ts (KEYWORD_ICONS)
    // Rule: a free-form slug containing a known keyword resolves to its icon,
    //       which differs from the generic FileText fallback.
    const icon = iconForType("my_medical_form");
    expect(icon).not.toBe(FileText);
  });

  it("returns FileText for an unknown type with no matching keyword", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: a slug with no keyword match falls back to FileText.
    expect(iconForType("zyzzyva_document")).toBe(FileText);
  });
});

describe("iconForType — custom icons", () => {
  it("returns the component for a custom icon name set via setCustomTypeIcons", () => {
    // Doc:  code-map.md → typeIcons.ts (setCustomTypeIcons)
    // Rule: after setCustomTypeIcons({work_order: "Briefcase"}), iconForType("work_order")
    //       returns the Briefcase component, not FileText.
    setCustomTypeIcons({ work_order: "Briefcase" });
    const icon = iconForType("work_order");
    expect(icon).toBe(ICON_NAME_MAP["Briefcase"]);
    expect(icon).not.toBe(FileText);
  });

  it("falls back to FileText when the custom icon name is not in ICON_NAME_MAP", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: if the stored icon name is unknown (e.g. a bad value in AppSettings),
    //       iconForType falls back through keyword matching and then to FileText.
    setCustomTypeIcons({ odd_type: "NonExistentIcon" });
    expect(iconForType("odd_type")).toBe(FileText);
  });

  it("custom icons do not affect built-in type resolution", () => {
    // Doc:  code-map.md → typeIcons.ts
    // Rule: setCustomTypeIcons cannot override a built-in type mapping.
    setCustomTypeIcons({ invoice: "Archive" });
    const icon = iconForType("invoice");
    // TYPE_ICONS is checked first, so "invoice" still returns its built-in icon
    expect(icon).not.toBe(ICON_NAME_MAP["Archive"]);
    expect(icon).not.toBe(FileText);
  });

  it("custom icons cleared between tests via beforeEach", () => {
    // Doc:  none — test isolation guard
    // Rule: setCustomTypeIcons({}) resets the cache so previous tests don't bleed.
    expect(iconForType("work_order")).toBe(FileText); // cleared by beforeEach
  });
});

describe("ICON_NAME_MAP completeness", () => {
  it("contains entries for all common extra icons used by the suggestion service", () => {
    // Doc:  code-map.md → typeIcons.ts (ICON_NAME_MAP)
    // Rule: every name in the backend ALLOWED_ICONS extra pool must exist in ICON_NAME_MAP
    //       so that icon names returned by the LLM can always be resolved.
    const expectedExtras = [
      "Archive", "Banknote", "BookOpen", "Briefcase", "Building", "Building2",
      "CalendarDays", "Clock", "CreditCard", "Flag", "FolderOpen", "Globe",
      "Lock", "MapPin", "Newspaper", "Package", "Phone", "Printer",
      "Scale", "Shield", "ShieldCheck", "ShoppingBag", "Tag", "Truck", "Users",
    ];
    for (const name of expectedExtras) {
      expect(ICON_NAME_MAP[name], `ICON_NAME_MAP missing "${name}"`).toBeDefined();
    }
  });
});
