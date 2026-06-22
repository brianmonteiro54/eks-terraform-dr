"""Ponto de entrada da Lambda: gera o Terraform em memória e faz push no GitLab."""
import json
import traceback
import urllib.error
from datetime import datetime, timezone

from .config import get_config
from .generator import generate_terraform_files
from .gitlab_api import GitLabAPI


def lambda_handler(event, context):
    print("EKS Terraform Exporter (find-or-create cross-account + boto3 + GitLab + retry) - Iniciando...")
    event = event or {}
    config = get_config()
    # Parâmetros: o evento tem precedência sobre as variáveis de ambiente.
    cluster_name = event.get('cluster_name', config['cluster_name'])
    region = event.get('region', config['region'])
    capture_full_vpc = event.get('capture_full_vpc', config['capture_full_vpc'])
    gitlab_token = config['gitlab_token']
    # Validações de pré-requisitos.
    if not gitlab_token:
        return {'statusCode': 500, 'body': json.dumps(
            {'status': 'error', 'error': 'GITLAB_TOKEN não configurado (ou Secret não resolvido).'})}
    missing = [k for k, v in {
        'EKS_CLUSTER_NAME (ou event.cluster_name)': cluster_name,
        'AWS_REGION_EKS (ou event.region)': region,
        'GITLAB_REPO': config['gitlab_repo'],
        'GITLAB_BRANCH': config['gitlab_branch'],
    }.items() if not v]
    if missing:
        return {'statusCode': 400, 'body': json.dumps(
            {'status': 'error', 'error': 'Parâmetros obrigatórios ausentes: ' + ', '.join(missing)})}
    print(f"Cluster: {cluster_name} | Região: {region} | "
          f"Captura: {'VPC inteira' if capture_full_vpc else 'apenas subnets do cluster'}")
    try:
        # 1. Gera todos os arquivos do módulo Terraform EM MEMÓRIA (find-or-create).
        generated = generate_terraform_files(cluster_name, region, capture_full_vpc=capture_full_vpc)
        # 2. Monta o commit: prefixa cada caminho relativo com clusters/<cluster>/.
        base_dir = f"clusters/{cluster_name}"
        files_to_commit = [
            {'path': f"{base_dir}/{relpath}", 'content': content}
            for relpath, content in generated.items()
        ]
        print(f"Preparando commit de {len(files_to_commit)} arquivo(s) em {base_dir}/...")
        # 3. Push para o GitLab (com retentativa p/ concorrência entre Lambdas no branch).
        gitlab = GitLabAPI(
            config['gitlab_url'],
            gitlab_token,
            config['gitlab_repo'],
            max_retries=config['gitlab_push_max_retries'],
            base_delay=config['gitlab_push_base_delay'],
            max_delay=config['gitlab_push_max_delay'],
        )
        commit_message = f"[Auto] {cluster_name} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        result = gitlab.commit_files(files_to_commit, config['gitlab_branch'], commit_message)
        commit_id = (result or {}).get('id')
        print(f"Commit realizado: {str(commit_id or 'N/A')[:8]}")
        return {'statusCode': 200, 'body': json.dumps(
            {'status': 'success', 'commit_id': commit_id, 'files': len(files_to_commit)})}
    except urllib.error.HTTPError as e:
        error_msg = f"GitLab API Error {e.code}"
        if e.code == 401:
            error_msg = "Token inválido ou expirado"
        elif e.code == 403:
            error_msg = "Token sem permissão"
        print(f"Erro: {error_msg}")
        return {'statusCode': 500, 'body': json.dumps({'status': 'error', 'error': error_msg})}
    except Exception as e:
        print(f"Erro: {str(e)}")
        traceback.print_exc()
        return {'statusCode': 500, 'body': json.dumps({'status': 'error', 'error': str(e)})}
