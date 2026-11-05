"""
Servidor HTTP Seguro para o Painel Santiago (EDEC)
Serve diretamente o painel_santiago.html na raiz (/) sem expor ficheiros .env ou .xlsx.
"""
import os
import socket
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORTA = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class PainelHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _rotear_painel(self):
        caminho = self.path.split("?", 1)[0]
        if caminho in ("/", "/index.html", "/painel", "/painel_santiago.html"):
            self.path = "/painel_santiago.html"
            return True
        if caminho == "/config_santiago.js":
            self.path = "/config_santiago.js"
            return True
        if caminho in ("/apresentacao", "/apresentacao.html", "/apresentacao_edec_administracao.html"):
            self.path = "/apresentacao_edec_administracao.html"
            return True
        self.send_error(404, "Acesso restrito apenas ao Painel Santiago e Tabela Story Executivo.")
        return False

    def do_GET(self):
        if self._rotear_painel():
            return super().do_GET()

    def do_HEAD(self):
        if self._rotear_painel():
            return super().do_HEAD()


def obter_ips_locais():
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


if __name__ == "__main__":
    ips = obter_ips_locais()
    print("=" * 68)
    print(" SERVIDOR DO PAINEL SANTIAGO (EDEC) ATIVO")
    print("=" * 68)
    print(f" -> No Computador: http://localhost:{PORTA}")
    for ip in ips:
        print(f" -> No Telemovel (Mesmo Wi-Fi / Rede): http://{ip}:{PORTA}")
    print("=" * 68)
    server = HTTPServer(("0.0.0.0", PORTA), PainelHandler)
    server.serve_forever()
