export type EmailType =
  | "rate_confirmation" | "carrier_rate_confirmation" | "customer_rate_confirmation"
  | "pod" | "delivery_confirmation" | "carrier_invoice"
  | "booking_confirmation" | "pickup_confirmation"
  | "eta_update" | "tracking_update" | "general"
  | "payment_escalation" | "bol" | "packing_list"
  | "customer_correspondence" | "internal"
  | "customs_doc" | "detention_demurrage"
  | "carrier_rate" | "customer_rate" | "detention" | "appointment"
  | "invoice" | "delivery_update" | "rate_outreach"
  | "carrier_rate_response" | "warehouse_rate";

export interface EmailThread {
  id: string;
  efj: string | null;
  subject: string;
  sender: string;
  date: string;
  latest_message_date: string;
  type: string;
  priority: number;
  email_count: number;
  matched: boolean;
  needs_reply: boolean;
  is_high_priority: boolean;
}

export interface Email extends EmailThread {
  thread_id: string;
  body_html?: string;
  body_text?: string;
}

export interface InboxStats {
  total_threads: number;
  needs_reply: number;
  unmatched: number;
  high_priority: number;
}
