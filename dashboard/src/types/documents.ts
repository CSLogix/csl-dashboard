export type DocType =
  | "customer_rate" | "carrier_rate" | "pod" | "bol"
  | "carrier_invoice" | "packing_list" | "msds" | "email" | "other";

export interface Document {
  id: string;
  efj: string;
  doc_type: DocType;
  doc_type_label: string;
  filename: string;
  uploaded_at: string;
  size: number;
  url?: string;
  indexed?: boolean;
}

export type DocSummary = Record<string, Partial<Record<string, number>>>;

export interface BillingReadiness {
  ready: boolean;
  missing: string[];
  present: string[];
}
