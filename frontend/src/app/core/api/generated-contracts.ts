// Generated from authoritative Pydantic request and response models.
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
  density_g_cm3: number | null;
  nozzle_min_c: number | null;
  nozzle_max_c: number | null;
  bed_min_c: number | null;
  bed_max_c: number | null;
  gtin: string;
  manufacturer_sku: string;
  slicer_preset: string;
  low_stock_threshold_g: number;
  target_stock_g: number;
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
  stock_revision: number;
  opened: boolean;
  status: "sealed" | "opened" | "empty";
  location: string;
  notes: string;
  created_at: string;
  archived_at: string | null;
  tare_g: number;
  purchase_price_cents: number | null;
  purchase_currency: string;
  purchased_on: string | null;
  batch: string;
  brand: string;
  product_name: string;
  material: string;
  color_name: string;
  color_hex: string;
  diameter_mm: number;
  low_stock_threshold_g: number;
}

export interface ApiSpoolPage {
  items: ApiSpool[];
  next_cursor: number | null;
}

export interface ApiPrinter {
  id: number;
  name: string;
  kind: "moonraker" | "octoprint" | "bambu";
  base_url: string;
  token_env: string;
  serial: string;
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
  auto_account_bambu: boolean;
  last_progress_percent: number | null;
  last_layer_num: number | null;
  total_layer_num: number | null;
  status: "pending" | "printing" | "completed" | "needs_review" | "cancelled";
  accounting_status: "pending" | "needs_review" | "debited" | "discarded";
  accounting_revision: number;
  accounting_method: "actual" | "estimated" | "discard" | null;
  movement_id: number | null;
  note: string;
  external_job_id: string | null;
  observed_printing: number;
  created_at: string;
  created_by: number | null;
  updated_at: string;
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

export interface ApiMovement {
  id: number;
  spool_id: number;
  spool_uid: string;
  kind: "initial" | "consume" | "adjust";
  delta_g: number;
  remaining_after_g: number;
  note: string;
  created_at: string;
  source: string;
  source_ref: string | null;
  actor_id: number | null;
  actor_name: string | null;
  print_job_id: number | null;
  job_id: number | null;
  job_file_name: string | null;
  corrects_movement_id: number | null;
  accounting_operation_id: string | null;
  brand: string;
  product_name: string;
  material: string;
  color_name: string;
  color_hex: string;
}

export interface ApiMovementPage {
  items: ApiMovement[];
  next_cursor: number | null;
}

export interface ApiRestockItem {
  product_id: number;
  brand: string;
  name: string;
  material: string;
  color_name: string;
  color_hex: string;
  target_stock_g: number;
  remaining_g: number;
  reserved_g: number;
  available_g: number;
  active_spools: number;
  sealed_spools: number;
  suggested_g: number;
}

export interface ApiRestock {
  items: ApiRestockItem[];
}

export interface ApiSpoolBatch {
  items: ApiSpool[];
  label_url: string;
}

export interface ApiSlot {
  tool: number;
  spool_id: number;
  spool_uid: string;
  brand: string;
  product_name: string;
}

export interface ApiReadinessMaterial {
  tool: number;
  spool_id: number;
  estimated_g: number;
  remaining_g: number;
  archived_at: string | null;
  brand: string;
  product_name: string;
  own_reservation_g: number | null;
  others_reserved_g: number;
  loaded_tool: number | null;
  available_g: number;
  ready: boolean;
  loaded_match: boolean;
}

export interface ApiReadiness {
  job_id: number;
  status: string;
  ready: boolean;
  materials: ApiReadinessMaterial[];
  reserved: boolean;
}

export interface ApiInspectionMaterial {
  tool: number;
  estimated_g: number;
}

export interface ApiInspectionPlate {
  plate: number;
  materials: ApiInspectionMaterial[];
}

export interface ApiInspection {
  file_stored: boolean;
  verified: boolean;
  source: string;
  plates: ApiInspectionPlate[];
  needs_manual_estimate: boolean;
}

export interface ApiPrinterOperation {
  operation_id: string;
  printer_id: number;
  job_id: number;
  kind: "start" | "upload";
  state: "active" | "unknown";
  created_at: string;
  updated_at: string;
}

export interface ApiProductInput {
  brand: string;
  name: string;
  material: string;
  color_name: string;
  color_hex?: string;
  diameter_mm?: number;
  notes?: string;
  density_g_cm3?: number | null;
  nozzle_min_c?: number | null;
  nozzle_max_c?: number | null;
  bed_min_c?: number | null;
  bed_max_c?: number | null;
  gtin?: string;
  manufacturer_sku?: string;
  slicer_preset?: string;
  low_stock_threshold_g?: number;
  target_stock_g?: number;
}

export interface ApiSpoolInput {
  product_id: number;
  initial_g: number;
  remaining_g?: number | null;
  opened?: boolean;
  location?: string;
  notes?: string;
  tare_g?: number;
  purchase_price_cents?: number | null;
  purchase_currency?: string;
  purchased_on?: string | null;
  batch?: string;
}

export interface ApiSpoolUpdate {
  opened?: boolean | null;
  location?: string | null;
  notes?: string | null;
  tare_g?: number | null;
  purchase_price_cents?: number | null;
  purchase_currency?: string | null;
  purchased_on?: string | null;
  batch?: string | null;
  expected_location?: string | null;
}

export interface ApiSpoolBatchInput {
  count: number;
  spool: ApiSpoolInput;
  request_id?: string | null;
}

export interface ApiMovementInput {
  kind: "consume" | "adjust";
  grams: number;
  note?: string;
}

export interface ApiWeighInput {
  gross_g: number;
  tare_g?: number | null;
  expected_stock_revision?: number | null;
  note?: string;
}

export interface ApiDryingInput {
  temperature_c: number;
  duration_minutes: number;
  dried_at: string;
  note?: string;
}

export interface ApiJobInput {
  printer_id: number;
  spool_id: number;
  file_name: string;
  estimated_g: number;
  auto_account_bambu?: boolean;
  note?: string;
}

export interface ApiMaterialMapping {
  tool: number;
  spool_id: number;
  estimated_g: number;
}

export interface ApiMultiJobInput {
  printer_id: number;
  file_name: string;
  materials: ApiMaterialMapping[];
  auto_account_bambu?: boolean;
  note?: string;
}

export interface ApiResolution {
  action: string;
}

export interface ApiSlotAssignment {
  spool_id: number;
}

export interface ApiActualMaterial {
  spool_id: number;
  actual_g: number;
}

export interface ApiConsumptionMeasurement {
  spool_id: number;
  gross_g: number;
  tare_g?: number | null;
  expected_stock_revision: number;
  scale_event_id?: number | null;
}

export interface ApiConsumptionInput {
  mode: "actual" | "estimated" | "discard";
  materials?: ApiActualMaterial[];
  measurements?: ApiConsumptionMeasurement[];
  reason: string;
  expected_updated_at?: string | null;
  expected_accounting_revision?: number | null;
  request_id?: string | null;
}

export interface ApiConsumptionSpool {
  spool_id: number;
  spool_uid: string;
  product_name: string;
  brand: string;
  estimated_g: number;
  accounted_g: number;
  initial_g: number;
  remaining_g: number;
  tare_g: number;
  stock_revision: number;
  archived: boolean;
  last_movement_id: number | null;
  measurement_reconciliation_required?: boolean;
  last_measured_g?: number | null;
  last_measured_at?: string | null;
}

export interface ApiAccountingOperation {
  id: string;
  mode: "actual" | "estimated" | "discard";
  reason: string;
  actor_id: number | null;
  actor_name: string | null;
  created_at: string;
  accounting_revision: number;
}

export interface ApiConsumption {
  job_id: number;
  status: string;
  accounting_status: string;
  accounting_method: "actual" | "estimated" | "discard" | null;
  accounting_revision: number;
  accounting_note: string;
  updated_at: string;
  materials: ApiConsumptionSpool[];
  operations: ApiAccountingOperation[];
  operation_id?: string | null;
  duplicate?: boolean;
}

export interface ApiJobCount {
  status: string;
  count: number;
}

export interface ApiPollerStatus {
  status: "starting" | "running" | "waiting" | "stopped" | "failed";
  interval_seconds: number;
  started_at: string | null;
  last_cycle_at: string | null;
  last_success_at: string | null;
  last_heartbeat_at: string | null;
  last_error: string | null;
  lease_held: boolean;
  lease_owner?: string | null;
  lease_expires_at: string | null;
}

export interface ApiPrinterDiagnostics {
  id: number;
  name: string;
  enabled: boolean;
  active_jobs: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  consecutive_failures: number;
  last_error: string;
  observation_age_seconds: number | null;
  freshness: "never" | "current" | "stale" | "disabled";
}

export interface ApiUnresolvedCommand {
  id: string;
  printer_id: number;
  printer_name: string;
  job_id: number | null;
  action: string;
  state: string;
  created_at: string;
  updated_at: string;
}

export interface ApiBackupStatus {
  status: "never" | "ready" | "failed";
  last_success_at: string | null;
  last_size_bytes: number | null;
  last_error: string | null;
}

export interface ApiStorageStatus {
  database_bytes: number;
  wal_bytes: number;
  free_bytes: number;
  reserve_bytes: number;
  low_space: boolean;
}

export interface ApiRestoreStatus {
  last_restored_at: string | null;
  requires_token_reissue: boolean;
}

export interface ApiSlicerStatus {
  enabled: boolean;
  configured: boolean;
}

export interface ApiMaterialMappingWarning {
  job_id: number;
  file_name: string;
  status: string;
  job_estimate_g: number;
  material_estimate_g: number;
  material_count: number;
}

export interface ApiPrinterOperationDiagnostics {
  printer_id: number;
  printer_name: string;
  operation_id: string;
  job_id: number;
  kind: "start" | "upload";
  state: "active" | "unknown";
  created_at: string;
  updated_at: string;
}

export interface ApiDiagnostics {
  version: string;
  schema_version: number;
  status: "ok" | "degraded";
  jobs: ApiJobCount[];
  uncertain_commands: number;
  commands: ApiUnresolvedCommand[];
  poller: ApiPollerStatus;
  printers: ApiPrinterDiagnostics[];
  backup: ApiBackupStatus;
  storage: ApiStorageStatus;
  restore: ApiRestoreStatus;
  slicer: ApiSlicerStatus;
  material_mapping_warnings: ApiMaterialMappingWarning[];
  printer_operations: ApiPrinterOperationDiagnostics[];
}

export interface ApiAlert {
  id: string;
  category: "low_stock" | "job_review" | "printer_offline";
  severity: "warning" | "error";
  title: string;
  message: string;
  entity_type: "spool" | "print_job" | "printer";
  entity_id: string;
}

export interface ApiAlerts {
  schema_version: "1";
  instance_epoch: string;
  generated_at: string;
  truncated: boolean;
  alerts: ApiAlert[];
}

export interface ApiCsvPreview {
  dry_run: boolean;
  products_created: number;
  products_skipped: number;
  spools_created: number;
  spools_skipped: number;
}

export interface ApiSpoolmanPreview {
  dry_run: boolean;
  products_created: number;
  products_skipped: number;
  spools_created: number;
  spools_skipped: number;
  source: string;
  archived_skipped: number;
}

export interface ApiScaleMeasurement {
  id: number;
  source: string;
  event_id: string;
  spool_id: number;
  spool_uid: string;
  gross_g: number;
  tare_g: number | null;
  status: "pending" | "applied" | "discarded";
  received_at: string;
  reviewed_at: string | null;
  measured_at: string | null;
  net_g: number | null;
  captured_stock_revision: number | null;
  captured_tare_g: number | null;
  review_note: string | null;
  accounting_operation_id: string | null;
  stock_revision: number;
  remaining_g: number;
  current_tare_g: number;
  brand: string;
  product_name: string;
  stale: boolean;
  stale_reason: string | null;
  blocking_job_ids: number[];
}
