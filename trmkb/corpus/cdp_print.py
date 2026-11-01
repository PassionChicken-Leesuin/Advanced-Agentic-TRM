"""
Chrome DevTools Protocol 로 웹 페이지를 '사람이 보는 화면 그대로' PDF 로 인쇄.

일반 --print-to-pdf 의 두 문제를 해결한다.
  1) 쿠키 동의 창(Osano 등)이 모든 쪽에 겹침 → 동의 관리 스크립트 URL 을 차단
  2) 스크롤 애니메이션(Webflow 등)으로 본문이 투명(opacity:0) 상태로 인쇄됨 → 끝까지 스크롤한 뒤,
     남은 opacity:0 인라인 스타일만 보이게 강제
원본 HTML 파일은 따로 바이트 그대로 저장하므로, 이 PDF 는 열람용 사본이다.
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import websocket

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
BLOCK = ["*osano.com*", "*cookiebot*", "*onetrust*", "*cookielaw*", "*googletagmanager*", "*hotjar*", "*hs-scripts*", "*hsforms*"]
REVEAL_JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const H = () => document.body.scrollHeight;
  for (let y = 0; y < H(); y += Math.max(400, innerHeight * 0.8)) { window.scrollTo(0, y); await sleep(120); }
  window.scrollTo(0, 0); await sleep(300);
  const st = document.createElement('style');
  st.textContent = `[style*="opacity:0"],[style*="opacity: 0"]{opacity:1!important;transform:none!important}
    [class*="osano"],[id*="osano"],[class*="cookie"],[id*="cookie"]{display:none!important}`;
  document.head.appendChild(st);
  document.querySelectorAll('img[loading="lazy"]').forEach(i => i.loading = 'eager');
  await sleep(800);
  return document.body.innerText.length;
})()
"""


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Printer:
    def __init__(self, profile: Path):
        self.port = _free_port()
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--lang=en-US",
                                      f"--remote-debugging-port={self.port}", f"--user-data-dir={profile}",
                                      "--window-size=1366,900", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1); break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        self._id = 0

    def _ws(self):
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=5).read())
        page = next(t for t in targets if t["type"] == "page")
        return websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)

    def _call(self, ws, method, params=None):
        self._id += 1
        mid = self._id
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def print_pdf(self, url: str, out: Path, settle: float = 4.0) -> int:
        """반환: 페이지 본문 글자 수 (0 이면 실패로 간주)."""
        ws = self._ws()
        try:
            self._call(ws, "Network.enable")
            self._call(ws, "Network.setBlockedURLs", {"urls": BLOCK})
            self._call(ws, "Page.enable")
            self._call(ws, "Page.navigate", {"url": url})
            time.sleep(settle)
            r = self._call(ws, "Runtime.evaluate", {"expression": REVEAL_JS, "awaitPromise": True, "returnByValue": True})
            n = int(r.get("result", {}).get("value") or 0)
            pdf = self._call(ws, "Page.printToPDF", {"printBackground": True, "preferCSSPageSize": False,
                                                     "paperWidth": 8.27, "paperHeight": 11.69,
                                                     "marginTop": 0.3, "marginBottom": 0.3, "marginLeft": 0.3, "marginRight": 0.3})
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(pdf["data"]))
            return n
        finally:
            ws.close()

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
