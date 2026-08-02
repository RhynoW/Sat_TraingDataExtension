"""Client side of the SSA-RAG app-to-app dialogue mailbox.

Counterpart of F:\\GitHub\\SSA-RAG\\scripts\\ask.py's --chat-send/--chat-listen:
a plain JSONL mailbox both processes append to and poll. This is operational
coordination between the two apps (e.g. "is the service up?", "sending query
#2 now") — it never touches the RAG pipeline, LLM, or vector store.

Protocol (must stay in sync with scripts/ask.py on the SSA-RAG side):
    - mailbox file: <SSA-RAG>/logs/app_dialogue.jsonl
    - record:  {"timestamp": ISO-8601 UTC, "sender": "client"|"server", "message": str}
    - either side ends the conversation by sending the literal message "#Over#"
    - on receiving a message, the server first replies "#Echo#" as a delivery
      acknowledgement before any substantive reply (2026-07-03 extension);
      wait_for_reply() records it on self.last_echo and keeps waiting

Usage:
    from app_dialogue_client import DialogueClient

    chat = DialogueClient()                       # sender="client"
    chat.send("127.0.0.1:8000 服務是否啟動?")
    reply = chat.wait_for_reply(timeout=60)       # dict or None on timeout
    chat.send("送出第 2 筆 SSA-RAG 查詢")
    chat.end()                                    # sends #Over#

CLI:
    python app_dialogue_client.py --send "可以傳送SSA-RAG測試了嗎?"
    python app_dialogue_client.py --listen
    python app_dialogue_client.py --send "#Over#"
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DIALOGUE_LOG_PATH = Path(os.getenv(
    "SSA_RAG_DIALOGUE_LOG",
    r"F:\GitHub\SSA-RAG\logs\app_dialogue.jsonl",
))
DIALOGUE_END = "#Over#"
DIALOGUE_ECHO = "#Echo#"   # Server 收訊後的送達確認（非實質回覆）


class DialogueClient:
    def __init__(self, sender: str = "client", mailbox: Path = DIALOGUE_LOG_PATH):
        self.sender = sender
        self.other = "server" if sender == "client" else "client"
        self.mailbox = Path(mailbox)
        # start reading after whatever is already in the mailbox
        self._seen = len(self.read_all())

    # ── mailbox primitives ───────────────────────────────────────────────
    def read_all(self) -> list[dict]:
        if not self.mailbox.exists():
            return []
        records = []
        with self.mailbox.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip().strip("\x00")
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # 兩個程序同時 append 或寫入中斷可能留下損壞行——跳過而非中斷
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
        return records

    def send(self, message: str) -> dict:
        self.mailbox.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sender": self.sender,
            "message": message,
        }
        with self.mailbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._seen = len(self.read_all())
        return record

    # ── conversation helpers ─────────────────────────────────────────────
    def new_messages(self) -> list[dict]:
        """Unread records from the other side (advances the read cursor)."""
        records = self.read_all()
        fresh = [r for r in records[self._seen:] if r["sender"] == self.other]
        self._seen = len(records)
        return fresh

    def wait_for_reply(
        self, timeout: float = 60.0, poll: float = 1.0, skip_echo: bool = True
    ) -> dict | None:
        """Block until the other side sends a substantive message; None on timeout.

        依 2026-07-03 協定擴充，Server 收訊後會先回 "#Echo#" 送達確認。
        skip_echo=True（預設）時：#Echo# 記錄在 self.last_echo 但不當回覆返回，
        繼續在 timeout 內等待實質回覆；呼叫端可用 self.last_echo 判斷訊息已送達。
        """
        self.last_echo: dict | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for rec in self.new_messages():
                if skip_echo and rec["message"].strip() == DIALOGUE_ECHO:
                    self.last_echo = rec
                    continue
                return rec
            time.sleep(poll)
        return None

    def end(self) -> dict:
        """End the conversation from this side."""
        return self.send(DIALOGUE_END)


def _cli() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    parser = argparse.ArgumentParser(description="SSA-RAG app-to-app dialogue (client side)")
    parser.add_argument("--send", metavar="MESSAGE", help="Append one message and exit")
    parser.add_argument("--listen", action="store_true", help="Print new server messages until #Over# or Ctrl+C")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()

    chat = DialogueClient()
    if args.send is not None:
        chat.send(args.send)
        print(f"[client] 已送出：{args.send}")
        return
    if args.listen:
        print(f"[client] 監聽對話中（來源：server）— {chat.mailbox}")
        try:
            while True:
                for record in chat.new_messages():
                    msg = record["message"].strip()
                    if msg == DIALOGUE_ECHO:
                        print("[server] ✓ #Echo#（送達確認）")
                        continue
                    print(f"[server] {record['message']}")
                    if msg == DIALOGUE_END:
                        print("[client] 對方已結束對話。")
                        return
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            print("\n[client] 已手動中斷監聽。")
        return
    parser.error("use --send MESSAGE or --listen")


if __name__ == "__main__":
    _cli()
