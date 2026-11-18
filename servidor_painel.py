"""
Servidor local do Painel Santiago (porta 8765) com suporte para guardar
exportações CSV diretamente na pasta `santiago\\exportacoes\\`.
"""

import http.server
import json
import os
import re
import socketserver

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exportacoes")
HOST = "127.0.0.1"
PORT = 8765


class PainelHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_POST(self):
        if self.path != "/api/salvar-exportacao":
            self.send_error(404, "Endpoint não encontrado")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            nome_orig = os.path.basename(str(payload.get("filename", "exportacao.csv")))
            nome_seg = re.sub(r"[^A-Za-z0-9._\-]", "_", nome_orig)
            if not nome_seg.lower().endswith(".csv"):
                nome_seg += ".csv"
            conteudo = str(payload.get("content", ""))

            os.makedirs(EXPORT_DIR, exist_ok=True)
            destino = os.path.join(EXPORT_DIR, nome_seg)
            with open(destino, "w", encoding="utf-8-sig", newline="") as f:
                f.write(conteudo.lstrip("\ufeff"))

            resp = json.dumps({"ok": True, "filename": nome_seg, "path": destino}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as exc:
            err = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), PainelHandler) as httpd:
        print(f"Servidor Painel Santiago ativo em http://{HOST}:{PORT}/painel_santiago.html")
        print(f"Exportacoes CSV serao guardadas em: {EXPORT_DIR}")
        httpd.serve_forever()
