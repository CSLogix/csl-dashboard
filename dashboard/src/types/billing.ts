export interface UnbilledOrder {
  efj: string;
  account: string;
  customer_rate: number | null;
  carrier_pay: number | null;
  delivery_date: string;
  age_days: number;
  status: string;
  billing_status?: string;
}

export interface UnbilledStats {
  count: number;
  oldest_age: number;
  by_rep?: Array<{ rep: string; cnt: number }>;
}

export interface BillingFlowStep {
  key: string;
  label: string;
  color: string;
}
