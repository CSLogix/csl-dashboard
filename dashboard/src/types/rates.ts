export interface Quote {
  id: string;
  efj: string;
  lane: string;
  customer_rate: number;
  carrier_pay: number;
  margin: number;
  margin_pct: number;
  created_at: string;
  suggested_by: string;
  status: string;
}

export interface Lane {
  origin: string;
  destination: string;
  code: string;
  quotes: Quote[];
}

export interface CarrierRate {
  carrier: string;
  rate: number;
  date: string;
  source: string;
  efj?: string;
}

export interface MarketBenchmark {
  lane: string;
  avg_rate: number;
  min_rate: number;
  max_rate: number;
  sample_size: number;
  updated_at: string;
}
