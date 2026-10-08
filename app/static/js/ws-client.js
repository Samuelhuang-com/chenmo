// 會自動重連的 WebSocket。斷線時訊息先排隊，重連後依序送出。
export class Socket {
  constructor(path, onMessage, onState = () => {}) {
    this.url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
    this.onMessage = onMessage;
    this.onState = onState;
    this.queue = [];
    this.waiters = new Map();
    this.syncId = 0;
    this.delay = 1000;
    this.closedByUser = false;
    this._connect();
    this.pinger = setInterval(() => this.send({ type: "ping" }), 25000);
  }
  _connect() {
    this.onState("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.delay = 1000;
      this.onState("open");
      const q = this.queue.splice(0);
      q.forEach(m => ws.send(JSON.stringify(m)));
    };
    ws.onmessage = e => {
      let msg; try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === "synced" && this.waiters.has(msg.id)) {
        this.waiters.get(msg.id)(); this.waiters.delete(msg.id); return;
      }
      if (msg.type !== "pong") this.onMessage(msg);
    };
    ws.onclose = e => {
      this.onState("closed", e.code);
      if (this.closedByUser || e.code === 4404 || e.code === 4401) return;
      setTimeout(() => this._connect(), this.delay);
      this.delay = Math.min(this.delay * 2, 10000);
    };
  }
  send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
    else if (msg.type !== "ping") this.queue.push(msg);
  }
  // 等伺服器處理完先前所有訊息
  sync(timeoutMs = 5000) {
    const id = ++this.syncId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.waiters.delete(id); reject(new Error("timeout")); }, timeoutMs);
      this.waiters.set(id, () => { clearTimeout(timer); resolve(); });
      this.send({ type: "sync", id });
    });
  }
  close() { this.closedByUser = true; clearInterval(this.pinger); this.ws?.close(); }
}
