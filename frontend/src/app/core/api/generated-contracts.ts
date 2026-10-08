// Generated from Pydantic response models. Edit app/api/contracts.py instead.
// Regenerate: python scripts/generate_api_types.py

export interface ApiOverview {
  total_spools: number;
  remaining_g: number;
  opened_spools: number;
  sealed_spools: number;
  empty_spools: number;
  low_spools: number;
  total_products: number;
}

export interface ApiProduct {
  id: number;
  uid: string;
  brand: string;
  name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
  notes: string;
  created_at: string;
  updated_at: string;
  spool_count: number;
  total_remaining_g: number;
}

export interface ApiSpool {
  id: number;
  uid: string;
  product_id: number;
  initial_g: number;
  remaining_g: number;
  opened: boolean;
  status: "sealed" | "opened" | "empty";
  location: string;
  notes: string;
  created_at: string;
  archived_at: string | null;
  brand: string;
  product_name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
}

export interface ApiSpoolPage {
  items: ApiSpool[];
  next_cursor: number | null;
}

export interface ApiPrinter {
  id: number;
  name: string;
  kind: "moonraker" | "octoprint";
  base_url: string;
  token_env: string;
  enabled: number;
  created_at: string;
}

export interface ApiJobMaterial {
  tool: number;
  spool_id: number;
  estimated_g: number;
  movement_id: number | null;
  spool_uid: string;
  brand: string;
  product_name: string;
}

export interface ApiJob {
  id: number;
  printer_id: number;
  printer_name: string;
  spool_id: number;
  spool_uid: string;
  brand: string;
  product_name: string;
  file_name: string;
  estimated_g: number;
  status: "pending" | "printing" | "completed" | "needs_review" | "cancelled";
  accounting_status: "pending" | "needs_review" | "debited" | "discarded";
  movement_id: number | null;
  note: string;
  external_job_id: string | null;
  created_at: string;
  start_command_state: string | null;
  materials: ApiJobMaterial[];
}

export interface ApiCapabilities {
  schema_version: string;
  inventory_read: boolean;
  usage_write: boolean;
  printer_connections: boolean;
  slicer_connections: boolean;
}
