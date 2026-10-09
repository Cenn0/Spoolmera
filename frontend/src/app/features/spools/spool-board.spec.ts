import { describe, expect, it } from 'vitest';
import { spool } from '../../testing/fixtures';
import { orderSpools, spoolSort, storageLanes } from './spool-board';

describe('pure, localized spool sorting and warehouse lanes',()=>{
  const a=spool({id:3,location:'Shelf 10',remaining_g:700,color_name:'Blue'});
  const b=spool({id:1,uid:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',location:'Shelf 2',remaining_g:100,color_name:'Green'});
  const c=spool({id:2,uid:'cccccccc-cccc-4ccc-8ccc-cccccccccccc',location:'',remaining_g:500,color_name:'Red'});
  it('sorts a copy deterministically and never modifies source data',()=>{
    const rows=[a,b,c];
    expect(orderSpools(rows,'newest','en')).toEqual(rows);
    expect(orderSpools(rows,'remaining-low','en').map(x=>x.id)).toEqual([1,2,3]);
    expect(orderSpools(rows,'remaining-high','en').map(x=>x.id)).toEqual([3,2,1]);
    expect(orderSpools(rows,'location','en').map(x=>x.id)).toEqual([2,1,3]);
    expect(rows.map(x=>x.id)).toEqual([3,1,2]);
  });
  it('ignores unsupported stored sort preferences',()=>{
    expect(spoolSort('garbage')).toBe('newest');
    expect(spoolSort(null)).toBe('newest');
    expect(spoolSort('remaining-low')).toBe('remaining-low');
  });
  it('groups each loaded spool once and includes empty drop lanes',()=>{
    const lanes=storageLanes([a,b,c],['Shelf 12','Shelf 2'],'de-DE');
    expect(lanes.map(x=>x.location)).toEqual(['','Shelf 2','Shelf 10','Shelf 12']);
    expect(lanes.map(x=>x.spools.length)).toEqual([1,1,1,0]);
    expect(lanes.reduce((sum,lane)=>sum+lane.totalG,0)).toBe(1300);
    expect(a.location).toBe('Shelf 10');
  });
  it('handles empty inventory with a clear unassigned target',()=>{
    const lanes=storageLanes([],[],'en-US');
    expect(lanes).toEqual([{location:'',spools:[],totalG:0}]);
  });
});
