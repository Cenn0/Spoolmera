// jsdom has no native modal implementation. Browser smoke tests exercise the
// real dialog element; focused tests use these two DOM state transitions.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (): void { this.open = true; };
}
if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function (): void {
    this.open = false;
    this.dispatchEvent(new Event('close'));
  };
}
