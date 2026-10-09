import { computed, signal } from '@angular/core';
import { vi } from 'vitest';
import { ApiConsumption, ApiJob, ApiMovement, ApiOverview, ApiPrinter, ApiProduct, ApiSpool } from '../core/api/generated-contracts';
import { EMPTY_OVERVIEW } from '../models';

export function spool(overrides:Partial<ApiSpool>={}):ApiSpool{return {id:1,uid:'11111111-1111-4111-8111-111111111111',product_id:1,initial_g:1000,remaining_g:600,stock_revision:3,
  opened:true,status:'opened',location:'Shelf A',notes:'',created_at:'2026-10-01T12:00:00Z',archived_at:null,tare_g:200,
  purchase_price_cents:2000,purchase_currency:'EUR',purchased_on:'2026-10-01',batch:'Delivery A',brand:'Example',product_name:'Basic',
  material:'PLA',color_name:'Green',color_hex:'#227755',diameter_mm:1.75,low_stock_threshold_g:200,...overrides};}
export function product(overrides:Partial<ApiProduct>={}):ApiProduct{return {id:1,uid:'22222222-2222-4222-8222-222222222222',brand:'Example',name:'Basic',material:'PLA',color_name:'Green',color_hex:'#227755',diameter_mm:1.75,
  notes:'',density_g_cm3:null,nozzle_min_c:null,nozzle_max_c:null,bed_min_c:null,bed_max_c:null,gtin:'',manufacturer_sku:'',slicer_preset:'',low_stock_threshold_g:200,target_stock_g:2000,
  created_at:'2026-10-01T12:00:00Z',updated_at:'2026-10-01T12:00:00Z',spool_count:1,total_remaining_g:600,...overrides};}
export function printer(overrides:Partial<ApiPrinter>={}):ApiPrinter{return {id:1,name:'Workshop',kind:'moonraker',base_url:'http://192.168.1.20',token_env:'',enabled:1,created_at:'2026-10-01T12:00:00Z',...overrides};}
export function job(overrides:Partial<ApiJob>={}):ApiJob{return {id:1,printer_id:1,printer_name:'Workshop',spool_id:1,spool_uid:spool().uid,brand:'Example',product_name:'Basic',file_name:'part.gcode',estimated_g:100,status:'pending',
  accounting_status:'pending',accounting_revision:0,accounting_method:null,movement_id:null,note:'',external_job_id:null,observed_printing:0,created_at:'2026-10-01T12:00:00Z',created_by:1,updated_at:'2026-10-01T12:00:00Z',start_command_state:null,
  materials:[{tool:3,spool_id:1,estimated_g:100,movement_id:null,spool_uid:spool().uid,brand:'Example',product_name:'Basic'}],...overrides};}
export function movement(overrides:Partial<ApiMovement>={}):ApiMovement{return {id:1,spool_id:1,spool_uid:spool().uid,kind:'consume',delta_g:-50,remaining_after_g:600,note:'Part',created_at:'2026-10-01T12:00:00Z',source:'manual',source_ref:null,actor_id:1,actor_name:'editor',print_job_id:null,job_id:null,job_file_name:null,corrects_movement_id:null,accounting_operation_id:null,brand:'Example',product_name:'Basic',material:'PLA',color_name:'Green',color_hex:'#227755',...overrides};}
export function consumption(overrides:Partial<ApiConsumption>={}):ApiConsumption{return {job_id:1,status:'needs_review',accounting_status:'needs_review',accounting_method:null,accounting_revision:0,accounting_note:'',updated_at:'2026-10-01T12:00:00Z',
  materials:[{spool_id:1,spool_uid:spool().uid,product_name:'Basic',brand:'Example',estimated_g:100,accounted_g:0,initial_g:1000,remaining_g:600,tare_g:200,stock_revision:3,archived:false,last_movement_id:null,measurement_reconciliation_required:false,last_measured_g:null,last_measured_at:null}],operations:[],...overrides};}
export function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(reason:unknown)=>void;
  const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
export function authMock(role:'admin'|'editor'|'viewer'='admin'){
  const user=signal<{id:number;username:string;role:'admin'|'editor'|'viewer';csrf_token:string}|null>({id:1,username:role,role,csrf_token:'test'});
  return {user,ready:signal(true),error:signal(''),ensureReady:vi.fn().mockResolvedValue(undefined),isAdmin:computed(()=>user()?.role==='admin'),canEdit:computed(()=>!!user()&&user()?.role!=='viewer')};
}
export function inventoryMock(){
  const spools=signal([spool()]);return {spools,products:signal([product()]),movements:signal<ApiMovement[]>([]),overview:signal<ApiOverview>({...EMPTY_OVERVIEW,total_spools:1}),
    available:computed(()=>spools().filter(s=>s.remaining_g>0)),changed:signal(0),lastUpdated:signal<string|null>(null),ready:signal(true),loading:signal(false),error:signal(''),
    load:vi.fn().mockResolvedValue(true),movementsFor:vi.fn().mockResolvedValue([]),dryingRecords:vi.fn().mockResolvedValue([]),identifiers:vi.fn().mockResolvedValue([]),updateSpool:vi.fn().mockResolvedValue(undefined),
    createBatch:vi.fn(),spoolPage:vi.fn().mockResolvedValue({items:spools(),next_cursor:null}),movementPage:vi.fn().mockResolvedValue({items:[],next_cursor:null}),restock:vi.fn().mockResolvedValue({items:[]}),weigh:vi.fn().mockResolvedValue(undefined)};
}
export function workspaceMock(){return {printers:vi.fn().mockResolvedValue([printer()]),jobs:vi.fn().mockResolvedValue([job()]),printerCapabilities:vi.fn().mockResolvedValue({write_enabled:true,max_upload_bytes:1000000}),slicerProfiles:vi.fn().mockResolvedValue({enabled:false,profiles:[]}),
  printerSlots:vi.fn().mockResolvedValue([]),printerOperations:vi.fn().mockResolvedValue([]),createMultiJob:vi.fn().mockResolvedValue({id:2}),inspectFile:vi.fn(),startJob:vi.fn(),assignSlot:vi.fn().mockResolvedValue(undefined),unloadSlot:vi.fn().mockResolvedValue(undefined),
  consumption:vi.fn().mockResolvedValue(consumption()),reconcileConsumption:vi.fn().mockResolvedValue(consumption({accounting_status:'debited',accounting_revision:1})),};}
