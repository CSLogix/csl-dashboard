export type AlertType =
  | "status_change" | "delivered_needs_billing" | "tracking_behind"
  | "pod_received" | "needs_driver" | "doc_indexed"
  | "rate_response" | "payment_escalation" | "send_final_charges";

export interface Alert {
  id: string;
  type: AlertType;
  efj: string;
  account: string;
  rep: string;
  message: string;
  detail: string;
  timestamp: number;
  shipmentId: number;
}

export interface AlertTypeConfig {
  icon: string;
  color: string;
  label: string;
}

export interface EventAlert {
  id: string;
  type: string;
  efj: string;
  timestamp: string;
  data?: Record<string, unknown>;
}
