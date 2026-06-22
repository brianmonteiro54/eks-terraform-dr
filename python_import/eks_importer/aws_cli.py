"""Execução do AWS CLI na conta de ORIGEM (captura).

run_aws_command roda um comando e devolve o JSON. Falhas são acumuladas em
_CAPTURE_FAILURES (normalmente permissão IAM faltando) e listadas no relatório.
"""
import json
import subprocess
import shlex
import sys

_CAPTURE_FAILURES = []
def run_aws_command(cmd, profile=None):
    """Executa um comando AWS CLI e retorna o JSON de saída."""
    if profile:
        cmd += f" --profile {profile}"
    
    print(f"   ... Executando: {cmd.split(' --region')[0]}...") # Log curto
    
    try:
        # Usar shlex.split para lidar com comandos complexos
        result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout else None
    except subprocess.CalledProcessError as e:
        # Registra o comando que falhou (na ORIGEM, falha normalmente = permissão
        # IAM faltando, já que os recursos existem). O relatório lista no final.
        short = cmd.split(' --region')[0]
        if profile:
            short = short.replace(f" --profile {profile}", "")
        _CAPTURE_FAILURES.append((short.strip(), (e.stderr or "").strip()[:200]))
        print(f"⚠️  Aviso: Comando falhou (pode ser esperado): {cmd.split(' --region')[0]}", file=sys.stderr)
        print(f"    Stderr: {e.stderr.strip()}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"Erro: A saída do comando não foi um JSON válido: {cmd}", file=sys.stderr)
        return None
