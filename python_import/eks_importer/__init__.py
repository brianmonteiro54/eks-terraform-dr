"""eks_importer — captura um cluster EKS existente e gera Terraform modular
portável entre contas (estratégia find-or-create).

Uso:
    python -m eks_importer <nome-do-cluster> [regiao] [profile] [--cluster-subnets-only]
"""
from .generator import generate_modular_eks_terraform

__all__ = ["generate_modular_eks_terraform"]
__version__ = "2.0.0"
