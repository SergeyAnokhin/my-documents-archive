import {
  BookUser, IdCard, Car, Baby, Cross, Heart, HeartCrack, House, Plane,
  FileSignature, Handshake, UserCheck, Gavel, ReceiptText, Landmark, Receipt,
  Coins, Wallet, KeyRound, BadgeCheck, Umbrella, Stethoscope, Pill, ClipboardPlus,
  GraduationCap, Award, ClipboardList, School, FileCheck, FileBadge, ClipboardCheck,
  Stamp, Mail, Bell, Megaphone, Image, ScanLine, FileQuestion, FileText,
  type LucideIcon,
} from "lucide-react";

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

/** Returns the lucide icon for a document type, with keyword and default fallbacks. */
export function iconForType(type?: string | null): LucideIcon {
  if (!type) return FileText;
  const slug = type.trim().toLowerCase();
  if (TYPE_ICONS[slug]) return TYPE_ICONS[slug];
  for (const [kw, icon] of KEYWORD_ICONS) {
    if (slug.includes(kw)) return icon;
  }
  return FileText;
}
