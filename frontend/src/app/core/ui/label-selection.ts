import { Spool } from '../../models';
export const MAX_LABELS = 100;
export function addLabel(selected: readonly Spool[], spool: Spool): Spool[] {
  return selected.some(item => item.uid === spool.uid) || selected.length >= MAX_LABELS
    ? [...selected] : [...selected, spool];
}
export function reorderLabels(selected: readonly Spool[], uid: string, targetUid: string): Spool[] {
  if (uid === targetUid || !selected.some(item => item.uid === uid) || !selected.some(item => item.uid === targetUid)) return [...selected];
  const next = [...selected]; const from = next.findIndex(item => item.uid === uid), to = next.findIndex(item => item.uid === targetUid);
  next.splice(to, 0, next.splice(from, 1)[0]); return next;
}
