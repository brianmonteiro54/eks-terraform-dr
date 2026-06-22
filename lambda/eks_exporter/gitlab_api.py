"""Cliente GitLab: commit dos arquivos gerados, com retentativa para concorrência
entre Lambdas dando push no mesmo branch."""
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request


class GitLabAPI:
    # Códigos HTTP que indicam falha potencialmente transitória / de concorrência.
    #  - 400: o commits API costuma devolver 400 quando o arquivo "já existe"
    #         (corrida de 'create') ou quando o HEAD do branch mudou no meio do
    #         push. Como recalculamos as actions a cada tentativa, o retry resolve.
    #  - 409: conflito explícito de concorrência.
    #  - 429: rate limit.
    #  - 5xx: erro de servidor / Gitaly.
    # NÃO retentamos 401/403 (token) nem 404 (rota/projeto errado): repetir não ajuda.
    _RETRYABLE_STATUS = frozenset({400, 409, 429, 500, 502, 503, 504})

    def __init__(self, gitlab_url, token, repo_path,
                 max_retries=5, base_delay=1.0, max_delay=20.0):
        self.base_url = gitlab_url.rstrip('/')
        self.token = token
        self.project_id = urllib.parse.quote(repo_path, safe='')
        self.max_retries = max(1, int(max_retries))
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}/api/v4{endpoint}"
        headers = {"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"}
        body = json.dumps(data).encode('utf-8') if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            print(f"GitLab API Error {e.code}: {error_body}")
            raise e

    def file_exists(self, file_path, branch):
        encoded_path = urllib.parse.quote(file_path, safe='')
        try:
            self._request("GET", f"/projects/{self.project_id}/repository/files/{encoded_path}?ref={branch}")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def _build_actions(self, files, branch):
        """
        (Re)calcula as actions create/update com base no estado ATUAL do branch.
        É importante rodar isto a CADA tentativa: enquanto esta Lambda esperava,
        outra execução paralela pode ter criado o mesmo arquivo, transformando um
        'create' (que falharia com "already exists") em 'update' — e vice-versa.
        """
        actions = []
        for file_info in files:
            exists = self.file_exists(file_info['path'], branch)
            actions.append({
                "action": "update" if exists else "create",
                "file_path": file_info['path'],
                "content": file_info['content']
            })
            print(f"  {'update' if exists else 'create'}: {file_info['path']}")
        return actions

    def _backoff_delay(self, attempt):
        # Full jitter (recomendação AWS para retries distribuídos): espalha as
        # retentativas de Lambdas concorrentes para que não colidam de novo no
        # mesmo instante. attempt começa em 1.
        exp = self.base_delay * (2 ** (attempt - 1))
        capped = min(self.max_delay, exp)
        return random.uniform(0, capped)

    def commit_files(self, files, branch, commit_message):
        """
        Faz o commit dos arquivos com retentativa automática.
        Como várias Lambdas podem dar push no MESMO branch praticamente no mesmo
        segundo, o commit pode falhar por concorrência (arquivo recém-criado por
        outra execução, HEAD do branch movido, etc.). Tentamos novamente
        recalculando as actions e aplicando backoff exponencial com jitter.
        Observação: o commits API do GitLab NÃO é idempotente. Em um cenário raro
        (o commit chega ao servidor mas a resposta se perde), uma retentativa pode
        gerar um commit redundante/no-op. É um risco aceitável frente à falha
        definitiva do push, que é o problema que estamos resolvendo aqui.
        """
        endpoint = f"/projects/{self.project_id}/repository/commits"
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Recalcula create/update a cada tentativa (ver _build_actions).
                actions = self._build_actions(files, branch)
                result = self._request("POST", endpoint, {
                    "branch": branch,
                    "commit_message": commit_message,
                    "actions": actions
                })
                if attempt > 1:
                    print(f"  ✅ Push concluído na tentativa {attempt}/{self.max_retries}.")
                return result
            except urllib.error.HTTPError as e:
                # Erros de auth/permissão/rota não adiantam repetir.
                if e.code not in self._RETRYABLE_STATUS:
                    raise
                last_error = e
                reason = f"HTTP {e.code}"
            except OSError as e:
                # urllib.error.URLError, timeouts e quedas de conexão caem aqui.
                last_error = e
                reason = f"erro de rede ({e})"
            if attempt < self.max_retries:
                delay = self._backoff_delay(attempt)
                print(f"  ⚠️  Push falhou ({reason}) — tentativa {attempt}/{self.max_retries}. "
                      f"Outra Lambda pode ter feito push ao mesmo tempo. "
                      f"Repetindo em {delay:.1f}s...")
                time.sleep(delay)
            else:
                print(f"  ❌ Push falhou ({reason}) após {self.max_retries} tentativa(s).")
        # Esgotou as retentativas: propaga o último erro para o handler tratar.
        raise last_error
