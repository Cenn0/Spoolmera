import { FileDropComponent } from '../../core/ui/file-drop.component';
import { Component, HostListener, OnDestroy, OnInit, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '../../auth.service';
import { InventoryService, apiError } from '../../inventory.service';
import { NoticeService } from '../../dialog.service';
import { PrintJob, Printer, PrinterCapabilities, SliceProfiles, WorkspaceService, JobReadiness, FileInspection, PrinterOperation } from '../../workspace.service';
import { RequestOwner } from '../../core/request-owner';
import { I18nService, LocalizedMessage, TranslatePipe } from '../../core/i18n';
import { ConsumptionComponent } from './consumption.component';

type Mapping = {tool: number; spool_id: number; estimated_g: number | null};
type SlotSuggestion = {tool: number; spool_id: number; name: string; estimated_g: number};
@Component({standalone: true, imports: [FormsModule, RouterLink, ConsumptionComponent, TranslatePipe,FileDropComponent], templateUrl: './print-jobs.component.html'})
export class JobsComponent implements OnInit, OnDestroy {
  readonly i18n=inject(I18nService);
  readonly route=inject(ActivatedRoute);private readonly destroy=inject(DestroyRef);
  readonly focusedJob=signal<number|null>(null);
  readonly api = inject(WorkspaceService); readonly data = inject(InventoryService);
  readonly auth = inject(AuthService); readonly notice = inject(NoticeService);
  readonly printers = signal<Printer[]>([]); readonly jobs = signal<PrintJob[]>([]);
  readonly visibleJobs=computed(()=>this.jobs().filter(job=>!this.focusedJob()||job.id===this.focusedJob()));
  supportsJobDispatch(printerId:number):boolean{return this.printers().find(p=>p.id===printerId)?.kind!=='bambu';}
  readonly operations=signal<Record<number,PrinterOperation[]>>({});
  readonly busy = signal(false); readonly loading = signal(true); private readonly errorValue=signal<string|LocalizedMessage>('');readonly error=computed(()=>this.i18n.t(this.errorValue())); readonly grams=(value:number)=>this.i18n.grams(value);
  readonly readiness = signal<Record<number, JobReadiness>>({});
  readonly inspection = signal<FileInspection | null>(null);
  readonly slotSuggestions = signal<SlotSuggestion[]>([]);
  readonly uncertainUploads=signal<number[]>([]);
  readonly uncertainStarts = signal<number[]>([]);
  readonly accountingJob = signal<PrintJob | null>(null);
  readonly slicer = signal<SliceProfiles>({enabled: false, profiles: []});
  readonly capabilities = signal<PrinterCapabilities>({write_enabled: false, max_upload_bytes: 0});
  readonly extraMaterials = signal<Mapping[]>([]);
  readonly clearFor = signal<number | null>(null);
  private readonly inspectionOwner = new RequestOwner();
  private readonly refreshOwner = new RequestOwner();
  private readonly suggestionOwner = new RequestOwner();
  private inspectedFile: File | null = null;
  private suggestionContext = '';
  plateIndex = 0; firstTool = 0; printerId = 0; spoolId = 0;
  fileName = ''; estimatedG: number | null = null; upload: File | null = null; note = '';
  stlFile: File | null = null; sliceProfile = ''; clearReason = '';

  async ngOnInit(): Promise<void> {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroy)).subscribe(params=>{
      const id=Number(params.get('job'));this.focusedJob.set(Number.isInteger(id)&&id>0?id:null);
    });
    await this.refresh();
    this.printerId = this.printers().find(p => p.enabled)?.id || 0;
    this.spoolId = this.data.spools().find(s => s.remaining_g > 0)?.id || 0;
  }
  ngOnDestroy(): void { this.inspectionOwner.invalidate(); this.refreshOwner.invalidate(); this.suggestionOwner.invalidate(); }
  @HostListener('window:focus')
  async onFocus(): Promise<void> { if (!this.busy()) await this.refresh(); }
  async refresh(): Promise<boolean> {
    const request = this.refreshOwner.begin(); this.loading.set(true); this.errorValue.set('');
    try {
      const [printers, jobs] = await Promise.all([this.api.printers(), this.api.jobs()]);
      if (!this.refreshOwner.owns(request)) return false;
      this.printers.set(printers); this.jobs.set(jobs); this.readiness.set({});
      const operations=this.auth.canEdit()?await Promise.all(printers.map(async printer=>[printer.id,await this.api.printerOperations(printer.id)] as const)):[];
      if(!this.refreshOwner.owns(request))return false;
      this.operations.set(Object.fromEntries(operations));this.uncertainUploads.set([]);
      this.uncertainStarts.set([]);
      await this.data.load();
      if (this.auth.isAdmin()) {
        const [caps, profiles] = await Promise.all([this.api.printerCapabilities(), this.api.slicerProfiles()]);
        if (this.refreshOwner.owns(request)) {
          this.capabilities.set(caps); this.slicer.set(profiles);
          if (!profiles.profiles.includes(this.sliceProfile)) this.sliceProfile = profiles.profiles[0] || '';
        }
      }
      return true;
    } catch (error) { if (this.refreshOwner.owns(request)) this.errorValue.set(apiError(error)); return false; }
    finally { if (this.refreshOwner.owns(request)) this.loading.set(false); }
  }
  choose(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectMetadataFile(input.files?.[0]||null);input.value='';
  }
  rejectMetadataFile(message:string):void{this.selectMetadataFile(null);this.errorValue.set(message);}
  selectMetadataFile(file:File|null):void{
    this.upload=file;
    this.fileName = this.upload?.name || '';
    this.inspectionOwner.invalidate(); this.inspection.set(null); this.inspectedFile = null;
    this.firstTool = 0; this.estimatedG = null; this.extraMaterials.set([]);
    this.invalidateSuggestions(); this.errorValue.set('');
  }
  invalidateSuggestions(): void {
    this.suggestionOwner.invalidate(); this.slotSuggestions.set([]); this.suggestionContext = '';
  }
  changePlate(): void { this.invalidateSuggestions(); }
  private mappingKey(): string {
    return JSON.stringify({printer: this.printerId, firstTool: this.firstTool, weight: this.estimatedG,
      extra: this.extraMaterials().map(m => [m.tool, m.estimated_g])});
  }
  addMaterial(): void {
    const items = this.extraMaterials(), used = new Set([this.firstTool, ...items.map(item => item.tool)]);
    const tool = Array.from({length: 16}, (_, i) => i).find(value => !used.has(value));
    if (tool != null && items.length < 7) this.extraMaterials.set([...items, {tool, spool_id: 0, estimated_g: null}]);
    this.invalidateSuggestions();
  }
  removeMaterial(index: number): void {
    this.extraMaterials.update(items => items.filter((_, i) => i !== index)); this.invalidateSuggestions();
  }
  async inspect(): Promise<void> {
    const file = this.upload; if (!file || this.busy()) return;
    const request = this.inspectionOwner.begin(); this.busy.set(true); this.errorValue.set(''); this.inspection.set(null);
    try {
      const result = await this.api.inspectFile(file);
      if (!this.inspectionOwner.owns(request) || this.upload !== file) return;
      this.inspection.set(result); this.inspectedFile = file; this.plateIndex = 0; this.invalidateSuggestions();
      if (result.needs_manual_estimate) this.notice.show('No reliable material weights were found. Use manual mapping and enter the actual tool numbers and estimates.');
    } catch (error) { if (this.inspectionOwner.owns(request)) this.errorValue.set(apiError(error)); }
    finally { this.busy.set(false); }
  }
  applyInspection(): void {
    if (!this.inspectedFile || this.inspectedFile !== this.upload) return;
    const plate = this.inspection()?.plates[this.plateIndex]; if (!plate?.materials.length) return;
    const items = [...plate.materials].sort((a, b) => a.tool - b.tool);
    this.firstTool = items[0].tool; this.estimatedG = items[0].estimated_g; this.spoolId = 0;
    this.extraMaterials.set(items.slice(1).map(item => ({...item, spool_id: 0})));
    if (this.upload.name.toLowerCase().endsWith('.3mf')) this.fileName = '';
    this.upload = null; this.inspection.set(null); this.inspectedFile = null; this.inspectionOwner.invalidate();
    this.invalidateSuggestions();
    this.notice.show('Estimates copied. Select every physical roll and check the G-code filename on the printer before registering.');
  }
  useManualMapping(): void {
    if (this.upload?.name.toLowerCase().endsWith('.3mf')) this.fileName = '';
    this.upload = null; this.inspectedFile = null; this.inspection.set(null); this.inspectionOwner.invalidate();
    this.invalidateSuggestions();
  }
  async suggestLoadedSpools(): Promise<void> {
    if (this.busy() || !this.printerId) return;
    const mappings = [{tool: this.firstTool, estimated_g: this.estimatedG || 0}, ...this.extraMaterials().map(m => ({tool: m.tool, estimated_g: m.estimated_g || 0}))];
    if (mappings.some(m => m.estimated_g <= 0)) { this.errorValue.set('Enter a positive estimate for every tool first.'); return; }
    const context = this.mappingKey(), request = this.suggestionOwner.begin();
    this.busy.set(true); this.errorValue.set(''); this.slotSuggestions.set([]);
    try {
      const slots = await this.api.printerSlots(this.printerId);
      if (!this.suggestionOwner.owns(request) || this.mappingKey() !== context) return;
      const proposals = mappings.flatMap(mapping => {
        const slot = slots.find(item => item.tool === mapping.tool);
        const spool = this.data.spools().find(item => item.id === slot?.spool_id);
        return spool && spool.remaining_g >= mapping.estimated_g
          ? [{...mapping, spool_id: spool.id, name: spool.brand+' · '+spool.product_name+' · '+spool.color_name}] : [];
      });
      if (proposals.length !== mappings.length) { this.errorValue.set('Some tools have no recorded roll or insufficient material. Assign the rolls manually.'); return; }
      this.suggestionContext = context; this.slotSuggestions.set(proposals);
    } catch (error) { if (this.suggestionOwner.owns(request)) this.errorValue.set(apiError(error)); }
    finally { this.busy.set(false); }
  }
  applyLoadedSpools(): void {
    if (this.mappingKey() !== this.suggestionContext) { this.invalidateSuggestions(); return; }
    const suggestions = this.slotSuggestions();
    if (!suggestions.length || !window.confirm(this.i18n.t('Use these recorded slot assignments? Verify the physical rolls loaded in the printer.'))) return;
    this.spoolId = suggestions.find(item => item.tool === this.firstTool)?.spool_id || 0;
    this.extraMaterials.update(items => items.map(item => ({...item, spool_id: suggestions.find(s => s.tool === item.tool)?.spool_id || 0})));
    this.invalidateSuggestions();
  }
  async checkReadiness(job: PrintJob): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.errorValue.set('');
    try { const result = await this.api.readiness(job.id); this.readiness.update(old => ({...old, [job.id]: result})); }
    catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async setReservation(job: PrintJob, enabled: boolean): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.errorValue.set('');
    try { const result = enabled ? await this.api.reserve(job.id) : await this.api.release(job.id);
      this.readiness.update(old => ({...old, [job.id]: result})); this.notice.show(enabled ? 'Material reserved. No stock was consumed.' : 'Reservation released.');
    } catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  chooseStl(event: Event): void { this.stlFile = (event.target as HTMLInputElement).files?.[0] || null; }
  rejectStl(message:string):void{this.stlFile=null;this.errorValue.set(message);}
  async sliceModel(): Promise<void> {
    const file = this.stlFile; if (!file || !this.sliceProfile || this.busy()) return;
    this.busy.set(true); this.errorValue.set('');
    try {
      const result = await this.api.sliceStl(file, this.sliceProfile), url = URL.createObjectURL(result.content);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.name.replace(/\.stl$/i, '.gcode');
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 30000);
      this.notice.show(result.estimated
        ? this.i18n.message('G-code generated · estimated {amount} g. Inspect it before printing.', {amount: Number.isFinite(Number(result.estimated)) ? Number(result.estimated) : result.estimated})
        : 'G-code generated. Inspect it before printing.');
    } catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async uploadPending(job: PrintJob, event: Event): Promise<void> {
    const input = event.target as HTMLInputElement, file = input.files?.[0]; input.value = '';
    if (!file || this.busy() || this.uncertainUploads().includes(job.printer_id) || (this.operations()[job.printer_id]||[]).length) return;
    if (file.name !== job.file_name) { this.errorValue.set('Choose the exact registered G-code filename.'); return; }
    if (!window.confirm(this.i18n.t('Upload {file} to {printer}?', {file:file.name,printer:job.printer_name}))) return;
    this.busy.set(true);this.errorValue.set('');let failure='';this.uncertainUploads.update(ids=>[...ids,job.printer_id]);
    try{await this.api.uploadJob(job.id,file);this.notice.show('File transferred. Print not started.');}
    catch(error){failure=apiError(error);}
    finally{const refreshed=await this.refresh();if(!refreshed&&failure)this.uncertainUploads.update(ids=>ids.includes(job.printer_id)?ids:[...ids,job.printer_id]);if(failure)this.errorValue.set(this.i18n.message('{error} Review the printer operation before retrying an uncertain upload.',{error:this.i18n.message(failure)}));this.busy.set(false);}
  }
  async clearStart(job: PrintJob): Promise<void> {
    if (!this.auth.isAdmin() || this.busy() || this.clearFor() !== job.id || this.clearReason.trim().length < 10) return;
    if (!window.confirm(this.i18n.t('Have you checked that the printer is idle and this previous operation is no longer running? Releasing it permits a later operation.'))) return;
    this.busy.set(true); this.errorValue.set('');
    try {
      const commands = await this.api.jobCommands(job.id), last = commands.find(item => item.action === 'start');
      if (!last || !['unknown', 'acknowledged', 'confirmed'].includes(last.state)) throw new Error('No releasable start command was found. Refresh the job state.');
      await this.api.clearPrinterCommand(last.id, this.clearReason.trim());
      this.clearFor.set(null); this.clearReason = ''; await this.refresh(); this.notice.show('Start command cleared after verification.');
    } catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async start(job: PrintJob): Promise<void> {
    if (!this.auth.isAdmin() || this.busy() || this.uncertainStarts().includes(job.id) || this.uncertainUploads().includes(job.printer_id) || (job.start_command_state&&job.start_command_state!=='cleared') || (this.operations()[job.printer_id]||[]).length) return;
    if (!window.confirm(this.i18n.t('Start {file} on {printer}? The printer will physically begin printing.',{file:job.file_name,printer:job.printer_name}))) return;
    this.busy.set(true); this.errorValue.set(''); this.uncertainStarts.update(ids => [...ids, job.id]);
    let failure = '';
    try { await this.api.startJob(job.id); this.notice.show('Start acknowledged. Waiting for independently observed printer progress.'); }
    catch (error) { failure = apiError(error); }
    finally {
      const refreshed = await this.refresh();
      if (!refreshed) this.uncertainStarts.update(ids => ids.includes(job.id) ? ids : [...ids, job.id]);
      if (failure) this.errorValue.set(this.i18n.message(refreshed ? '{error} Review the refreshed command state.' : '{error} Start outcome is unknown. Refresh and verify the printer before retrying.', {error:this.i18n.message(failure)}));
      this.busy.set(false);
    }
  }
  async submit(): Promise<void> {
    if (this.busy() || !this.auth.canEdit()) return;
    if (this.upload) { this.errorValue.set('Inspect and apply the selected file, or switch to manual mapping first.'); return; }
    const materials = [{tool: this.firstTool, spool_id: this.spoolId, estimated_g: this.estimatedG}, ...this.extraMaterials()];
    if (!this.printerId || !this.fileName.trim() || materials.some(m => !Number.isInteger(m.tool) || m.tool < 0 || m.tool > 15 || !m.spool_id || !Number.isInteger(m.estimated_g) || Number(m.estimated_g) <= 0)) {
      this.errorValue.set('Select a printer and each physical roll, and enter tool numbers 0–15 and positive whole-gram estimates.'); return;
    }
    if (new Set(materials.map(m => m.tool)).size !== materials.length) { this.errorValue.set('Each tool number must be unique.'); return; }
    this.busy.set(true); this.errorValue.set('');
    try {
      await this.api.createMultiJob({printer_id: this.printerId, file_name: this.fileName.trim(), note: this.note,
        materials: materials.map(m => ({...m, estimated_g: Number(m.estimated_g)}))});
      this.fileName = ''; this.upload = null; this.estimatedG = null; this.note = ''; this.firstTool = 0;
      this.extraMaterials.set([]); this.inspection.set(null); this.invalidateSuggestions(); await this.refresh();
      this.notice.show('Print-job mapping registered. Transfer and start the file separately when ready.');
    } catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async poll(printerId: number): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.errorValue.set('');
    try { const state = await this.api.poll(printerId); await this.refresh(); this.notice.show(this.i18n.message('Printer: {state} · {jobs} job(s) updated.',{state:this.i18n.message(state.state),jobs:state.updated_jobs})); }
    catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async cancel(job: PrintJob): Promise<void> {
    if (this.busy() || !window.confirm(this.i18n.t('Stop tracking this job? The physical printer will continue. Review any material it has consumed.'))) return;
    this.busy.set(true); this.errorValue.set('');
    try { await this.api.cancelJob(job.id); await this.refresh(); this.notice.show('Tracking stopped. Review material consumption separately.'); }
    catch (error) { this.errorValue.set(apiError(error)); } finally { this.busy.set(false); }
  }
  async accountingSaved(): Promise<void> { this.accountingJob.set(null); await this.refresh(); }
}
