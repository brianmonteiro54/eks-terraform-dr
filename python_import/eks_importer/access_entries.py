"""Filtros de Access Entries automáticos do EKS (não gerenciados pelo Terraform)."""
import re

EXCLUDED_ACCESS_ENTRY_TYPES = [
    "EC2_LINUX",          # Node roles (eksWorkerNodeRole, AmazonEKSNodeRole)
    "EC2",                # Node role do Auto Mode (AmazonEKSAutoNodeRole) - criado automaticamente pelo EKS
    "FARGATE_LINUX",      # Fargate pod execution roles
]
# Padrões de ARNs que devem ser IGNORADOS
EXCLUDED_ARN_PATTERNS = [
    r".*AWSServiceRoleForAmazonEKS",  # Service-linked role automático
    r".*eksWorkerNodeRole",           # Role comum de worker nodes
    r".*AmazonEKSNodeRole",          # Role comum de nodes
    r".*AmazonEKSAutoNodeRole",  # (opcional) Role de node do Auto Mode
    r".*AmazonEKSFargatePodExecutionRole",  # Role do Fargate
    r".*AWSReservedSSO_AdministratorAccess",  # Roles de SSO Administrator
    r".*AWSBackupDefaultServiceRole" # Role do AWS Backup
]


def should_exclude_access_entry(entry):
    """
    Verifica se um access entry deve ser excluído do Terraform.
    Retorna (True, motivo) se deve ser excluído, (False, None) caso contrário.
    """
    principal_arn = entry.get('principalArn', '')
    entry_type = entry.get('type', '')
    
    # Verificar por tipo
    if entry_type in EXCLUDED_ACCESS_ENTRY_TYPES:
        return True, f"tipo {entry_type}"
    
    # Verificar por padrão de ARN
    for pattern in EXCLUDED_ARN_PATTERNS:
        if re.search(pattern, principal_arn):
            return True, f"padrão ARN {pattern}"
    
    return False, None
