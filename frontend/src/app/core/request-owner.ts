/** Associates asynchronous work with the input or view that requested it. */
export class RequestOwner {
  private revision = 0;
  begin(): number { return ++this.revision; }
  invalidate(): void { ++this.revision; }
  owns(revision: number): boolean { return revision === this.revision; }
}
