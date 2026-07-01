import {
  BookUser, IdCard, Car, Baby, Cross, Heart, HeartCrack, House, Plane,
  FileSignature, Handshake, UserCheck, Gavel, ReceiptText, Landmark, Receipt,
  Coins, Wallet, KeyRound, BadgeCheck, Umbrella, Stethoscope, Pill, ClipboardPlus,
  GraduationCap, Award, ClipboardList, School, FileCheck, FileBadge, ClipboardCheck,
  Stamp, Mail, Bell, Megaphone, Image, ScanLine, FileQuestion, FileText,
  // Extra icons available for custom document types
  Archive, Banknote, BookOpen, Briefcase, Building, Building2,
  CalendarDays, Clock, CreditCard, Flag, FolderOpen, Globe,
  Lock, MapPin, Newspaper, Package, Phone, Printer,
  Scale, Shield, ShieldCheck, ShoppingBag, Tag, Truck, Users,
  type LucideIcon,
} from "lucide-react";

// File-format (not content-type) helper — used to distinguish a Word document
// from the generic FileText fallback when no thumbnail/visual preview exists.
export const WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export function isWordDoc(mime?: string): boolean {
  return mime === WORD_MIME;
}

// Maps each document_type slug from the AI taxonomy (see backend
// services/ai_analysis.py) to a lucide icon that visually evokes the class.
const TYPE_ICONS: Record<string, LucideIcon> = {
  passport: BookUser,
  national_id: IdCard,
  driver_license: Car,
  birth_certificate: Baby,
  death_certificate: Cross,
  marriage_certificate: Heart,
  divorce_certificate: HeartCrack,
  residence_permit: House,
  visa: Plane,
  contract: FileSignature,
  agreement: Handshake,
  power_of_attorney: UserCheck,
  court_document: Gavel,
  invoice: ReceiptText,
  bank_statement: Landmark,
  receipt: Receipt,
  tax_document: Coins,
  payslip: Wallet,
  property_deed: KeyRound,
  title_certificate: BadgeCheck,
  insurance_policy: Umbrella,
  medical_certificate: Stethoscope,
  prescription: Pill,
  medical_record: ClipboardPlus,
  diploma: GraduationCap,
  certificate: Award,
  transcript: ClipboardList,
  student_id: School,
  permit: FileCheck,
  license: FileBadge,
  registration: ClipboardCheck,
  notarial_deed: Stamp,
  letter: Mail,
  notice: Bell,
  announcement: Megaphone,
  photo: Image,
  scan: ScanLine,
  unclassified: FileQuestion,
};

// Lookup map from icon name string → component.
// Used to resolve icon names returned by the backend icon-suggestion service.
// Must include every name in services/type_icon_suggestion.py ALLOWED_ICONS.
export const ICON_NAME_MAP: Record<string, LucideIcon> = {
  // Built-in type icons
  Archive, Award, Baby, BadgeCheck, Bell, BookUser,
  Car, ClipboardCheck, ClipboardList, ClipboardPlus, Coins,
  Cross, FileBadge, FileCheck, FileQuestion, FileSignature, FileText,
  GraduationCap, Gavel, Handshake, Heart, HeartCrack, House,
  IdCard, Image, KeyRound, Landmark, Mail, Megaphone,
  Pill, Plane, Receipt, ReceiptText, ScanLine, School,
  Stamp, Stethoscope, Umbrella, UserCheck, Wallet,
  // Extra icons for custom types
  Banknote, BookOpen, Briefcase, Building, Building2,
  CalendarDays, Clock, CreditCard, Flag, FolderOpen, Globe,
  Lock, MapPin, Newspaper, Package, Phone, Printer,
  Scale, Shield, ShieldCheck, ShoppingBag, Tag, Truck, Users,
};

// Substring keywords for free-form / non-taxonomy types entered via TypePicker.
// First match wins, so order from most to least specific.
const KEYWORD_ICONS: [string, LucideIcon][] = [
  ["passport", BookUser],
  ["birth", Baby],
  ["marriage", Heart],
  ["divorce", HeartCrack],
  ["visa", Plane],
  ["driver", Car],
  ["court", Gavel],
  ["invoice", ReceiptText],
  ["receipt", Receipt],
  ["bank", Landmark],
  ["tax", Coins],
  ["pay", Wallet],
  ["insurance", Umbrella],
  ["prescription", Pill],
  ["medical", Stethoscope],
  ["health", Stethoscope],
  ["diploma", GraduationCap],
  ["transcript", ClipboardList],
  ["student", School],
  ["deed", KeyRound],
  ["property", House],
  ["permit", FileCheck],
  ["license", FileBadge],
  ["registration", ClipboardCheck],
  ["notar", Stamp],
  ["contract", FileSignature],
  ["agreement", Handshake],
  ["letter", Mail],
  ["notice", Bell],
  ["announcement", Megaphone],
  ["photo", Image],
  ["scan", ScanLine],
  ["certificate", Award],
  ["id", IdCard],
];

// Module-level cache of custom type → icon name, populated at app startup
// and refreshed after the admin "Update Icons" action.
let _customIcons: Record<string, string> = {};

/** Updates the custom icon cache (called at startup and after admin update). */
export function setCustomTypeIcons(icons: Record<string, string>): void {
  _customIcons = icons;
}

// Module-level cache of custom type → multilingual names {en, fr, ru}.
let _customNames: Record<string, { en: string; fr: string; ru: string }> = {};

/** Updates the custom type names cache (called at startup). */
export function setCustomTypeNames(names: Record<string, { en: string; fr: string; ru: string }>): void {
  _customNames = names;
}

/** Returns a human-readable label for a document type slug.
 *  Looks up multilingual custom names first, then falls back to slug formatting.
 */
export function labelForType(type?: string | null, lang: "en" | "fr" | "ru" = "en"): string {
  if (!type) return "";
  const slug = type.trim().toLowerCase();
  const entry = _customNames[slug];
  if (entry?.[lang]) return entry[lang];
  return slug.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

/** Returns the lucide icon for a document type, including custom assignments. */
export function iconForType(type?: string | null): LucideIcon {
  if (!type) return FileText;
  const slug = type.trim().toLowerCase();

  if (TYPE_ICONS[slug]) return TYPE_ICONS[slug];

  const customIconName = _customIcons[slug];
  if (customIconName && ICON_NAME_MAP[customIconName]) return ICON_NAME_MAP[customIconName];

  for (const [kw, icon] of KEYWORD_ICONS) {
    if (slug.includes(kw)) return icon;
  }
  return FileText;
}
