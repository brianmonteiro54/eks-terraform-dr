"""Runner boto3 — substitui a coleta via AWS CLI / subprocess.

As funções collect_* e o gerador chamam run_aws_command(cmd, profile) passando uma
string "aws ...". Como boto3 devolve as MESMAS estruturas do AWS CLI (--output
json), basta traduzir a string para a chamada boto3 equivalente — toda a lógica a
jusante continua idêntica à versão CLI.
"""
import os
import shlex
import sys

import boto3
from botocore.exceptions import ClientError

# Comandos AWS que falharam durante a captura (na ORIGEM, falha normalmente =
# permissão IAM faltando). O relatório CLUSTER-INFO lista no final.
_CAPTURE_FAILURES = []
_BOTO3_CLIENTS = {}


def _get_client(service, region):
    key = (service, region)
    if key not in _BOTO3_CLIENTS:
        _BOTO3_CLIENTS[key] = boto3.client(service, region_name=region)
    return _BOTO3_CLIENTS[key]


# Flags do CLI que mapeiam para parâmetros do tipo LISTA no boto3 (os demais são
# escalares). Filtros (--filters/--filter) são tratados à parte.
# TransitGatewayIds entra aqui porque describe-transit-gateways --transit-gateway-ids
# espera uma LISTA no boto3 (a captura de TGW para replicação cross-account o usa).
_LIST_PARAMS = {"VpcIds", "SubnetIds", "GroupIds", "KeyNames", "DhcpOptionsIds",
                "Versions", "TransitGatewayIds"}


def _kebab_to_param(service, flag):
    """
    Converte a flag do CLI (kebab-case) para o nome do parâmetro boto3.
    EC2 e IAM usam PascalCase (VpcIds, RoleName); EKS usa camelCase (clusterName).
    """
    parts = flag.split('-')
    if service == 'eks':
        return parts[0] + ''.join(p.capitalize() for p in parts[1:])
    return ''.join(p.capitalize() for p in parts)


def _parse_filter_tokens(tokens):
    """Converte tokens 'Name=k,Values=v1,v2' do CLI em [{'Name':k,'Values':[...]}]."""
    filters = []
    current = None
    for tok in tokens:
        for piece in tok.split(','):
            if '=' in piece:
                k, v = piece.split('=', 1)
                if k == 'Name':
                    current = {'Name': v, 'Values': []}
                    filters.append(current)
                elif k == 'Values' and current is not None:
                    current['Values'].append(v)
            elif current is not None:
                current['Values'].append(piece)  # valor de continuação (Values=a,b,c)
    return filters


def _parse_aws_command(cmd):
    """
    Quebra 'aws <service> <operation> [--flag valor ...]' em
    (service, operation_snake_case, kwargs_boto3, region_override).
    Função PURA — testável sem boto3.
    """
    tokens = shlex.split(cmd)
    service = tokens[1]
    operation = tokens[2].replace('-', '_')
    region = None
    kwargs = {}
    i, n = 3, len(tokens)
    while i < n:
        tok = tokens[i]
        if not tok.startswith('--'):
            i += 1
            continue
        flag = tok[2:]
        values = []
        j = i + 1
        while j < n and not tokens[j].startswith('--'):
            values.append(tokens[j])
            j += 1
        if flag == 'region':
            region = values[0] if values else None
        elif flag in ('profile', 'output'):
            pass  # profile: ignorado (Lambda usa a role); output: sempre JSON no boto3
        elif flag == 'max-items':
            pass  # paginação tratada via paginator do boto3 (pega TUDO)
        elif flag in ('filters', 'filter'):
            kwargs['Filters' if flag == 'filters' else 'Filter'] = _parse_filter_tokens(values)
        else:
            param = _kebab_to_param(service, flag)
            if not values:
                kwargs[param] = True  # flag booleana (ex.: --include-public-key)
            elif param in _LIST_PARAMS:
                kwargs[param] = values
            else:
                kwargs[param] = values[0]
        i = j
    return service, operation, kwargs, region


def run_aws_command(cmd, profile=None):
    """
    Executa o equivalente boto3 do comando 'aws ...' e devolve o dict de resposta
    (mesma forma do --output json). Em falha de AWS (não encontrado / acesso negado /
    etc.) registra em _CAPTURE_FAILURES e devolve None — exatamente como o runner
    antigo (subprocess) devolvia None em exit != 0.
    Erros de parâmetro/operação (BUGS do tradutor) NÃO são silenciados: propagam para
    aparecer em teste/execução em vez de gerar Terraform incompleto silenciosamente.
    """
    service, operation, kwargs, region = _parse_aws_command(cmd)
    if not region:
        region = (os.environ.get('AWS_REGION')
                  or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1')
    client = _get_client(service, region)
    short = cmd.split(' --region')[0].strip()
    try:
        if client.can_paginate(operation):
            return client.get_paginator(operation).paginate(**kwargs).build_full_result()
        return getattr(client, operation)(**kwargs)
    except ClientError as e:
        _CAPTURE_FAILURES.append((short, str(e)[:200]))
        print(f"⚠️  Aviso: comando AWS falhou (pode ser esperado): {short} — {e}",
              file=sys.stderr)
        return None
