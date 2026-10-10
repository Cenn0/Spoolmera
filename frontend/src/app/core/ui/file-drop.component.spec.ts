import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileDropComponent } from './file-drop.component';

describe('file picker and drop use one validation boundary',()=>{
  let component:FileDropComponent,selected:File[],rejected:string[];
  beforeEach(()=>{
    const fixture=TestBed.createComponent(FileDropComponent);fixture.componentRef.setInput('accept','.csv');fixture.componentRef.setInput('maxBytes',10);
    component=fixture.componentInstance;selected=[];rejected=[];
    component.selected.subscribe(file=>selected.push(file));component.rejected.subscribe(error=>rejected.push(error));
  });
  it('accepts a supported file without changing its contents, name or identity',()=>{
    const file=new File(['abc'],'MixedCase.CSV',{type:'text/csv'});component.acceptFiles([file]);expect(selected).toEqual([file]);expect(selected[0]).toBe(file);expect(rejected).toEqual([]);
  });
  it.each([
    [[], 'Choose exactly one file. Nothing has been uploaded.'],
    [[new File(['x'],'a.csv'),new File(['y'],'b.csv')], 'Choose exactly one file. Nothing has been uploaded.'],
    [[new File(['x'],'script.html')], 'This file type is not supported here.'],
    [[new File([],'a.csv')], 'This file is empty.'],
    [[new File(['01234567890'],'a.csv')], 'This file exceeds the allowed upload size.'],
  ])('rejects unsupported input without emitting a selected file', (files,message)=>{
    component.acceptFiles(files as File[]);expect(selected).toEqual([]);expect(rejected).toEqual([message]);
  });
  it('handles nested drag targets without losing the drop indicator',()=>{
    const event={dataTransfer:{types:['Files']},preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as DragEvent;
    component.enter(event);component.enter(event);component.leave(event);expect(component.over()).toBe(true);
    component.leave(event);expect(component.over()).toBe(false);
  });
  it('ignores internal object drops rather than discarding an existing file preview',()=>{
    const event={dataTransfer:{types:['application/x-spoolmera-spool'],files:[]},preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as DragEvent;
    component.drop(event);expect(rejected).toEqual([]);expect(selected).toEqual([]);
  });
  it('picker and drop emit the same File object',()=>{
    const file=new File(['a'],'a.csv'),input={files:[file],value:'chosen'};
    component.choose({target:input} as unknown as Event);expect(input.value).toBe('');
    component.drop({dataTransfer:{files:[file],types:['Files']},preventDefault:vi.fn(),stopPropagation:vi.fn()} as unknown as DragEvent);
    expect(selected).toEqual([file,file]);
  });
});
