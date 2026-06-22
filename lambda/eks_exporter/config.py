"""Configuração da Lambda: resolução de secret (GitLab token) + variáveis de ambiente."""
import json
import os

import boto3


def get_secret_value(arn_or_value):
    """
    Se o valor for um ARN do Secrets Manager, busca o valor real.
    Se for um token direto, retorna ele mesmo.
    """
    if not arn_or_value or not arn_or_value.startswith("arn:aws:secretsmanager"):
        return arn_or_value
    print(f"Resolvendo Secret ARN: {arn_or_value}")
    try:
        # 1. Limpar o ARN (remover sufixos ::Chave se existirem, pois boto3 falha com eles)
        # Ex: arn:aws:...:secret:nome::GITLAB_TOKEN: -> arn:aws:...:secret:nome
        clean_arn = arn_or_value.split('::')[0]
        # 2. Extrair região do ARN para instanciar o client correto
        # arn:aws:secretsmanager:REGION:account...
        region = clean_arn.split(':')[3]
        client = boto3.client('secretsmanager', region_name=region)
        response = client.get_secret_value(SecretId=clean_arn)
        secret_string = response.get('SecretString')
        if not secret_string:
            print("Erro: SecretString vazio ou é binário.")
            return None
        # 3. Tentar parsear JSON
        try:
            secret_json = json.loads(secret_string)
            # Tenta encontrar a chave GITLAB_TOKEN
            if 'GITLAB_TOKEN' in secret_json:
                return secret_json['GITLAB_TOKEN']
            # Se não achar a chave exata, retorna o JSON inteiro (pode falhar depois)
            return secret_json
        except json.JSONDecodeError:
            # Não é JSON, retorna a string inteira (ex: token salvo como texto plano)
            return secret_string
    except Exception as e:
        print(f"ERRO CRÍTICO ao buscar secret: {str(e)}")
        # Retorna None para forçar erro explícito na validação depois
        return None


def get_config():
    # Pega o valor bruto da variável de ambiente
    raw_token = os.environ.get("GITLAB_TOKEN")
    # Resolve o valor real (busca na AWS se for ARN)
    real_token = get_secret_value(raw_token)
    return {
        "gitlab_url": os.environ.get("GITLAB_URL", "https://xxx.com.br"),
        "gitlab_repo": os.environ.get("GITLAB_REPO"),
        "gitlab_branch": os.environ.get("GITLAB_BRANCH"),
        "gitlab_token": real_token,
        "cluster_name": os.environ.get("EKS_CLUSTER_NAME"),
        "region": os.environ.get("AWS_REGION_EKS"),
        # Captura a VPC INTEIRA por padrão (recuperação na mesma conta). Defina
        # CAPTURE_FULL_VPC=false para capturar só a rede que o cluster usa (útil em
        # DR reaproveitando a VPC do destino).
        "capture_full_vpc": os.environ.get("CAPTURE_FULL_VPC", "true").strip().lower()
        not in ("false", "0", "no"),
        # --- Retentativa do push (concorrência entre Lambdas no mesmo branch) ---
        # Configuráveis por variável de ambiente, mas com default >= 5 conforme necessário.
        "gitlab_push_max_retries": int(os.environ.get("GITLAB_PUSH_MAX_RETRIES", "5")),
        "gitlab_push_base_delay": float(os.environ.get("GITLAB_PUSH_BASE_DELAY", "1.0")),
        "gitlab_push_max_delay": float(os.environ.get("GITLAB_PUSH_MAX_DELAY", "20.0")),
    }
