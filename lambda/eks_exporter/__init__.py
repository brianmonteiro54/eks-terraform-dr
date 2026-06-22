"""eks_exporter — Lambda que captura um cluster EKS existente e gera Terraform
modular portável entre contas (find-or-create), fazendo push no GitLab.

Handler: eks_exporter.handler.lambda_handler
(ou lambda_function.lambda_handler via shim na raiz do pacote de deploy)
"""
from .handler import lambda_handler

__all__ = ["lambda_handler"]
__version__ = "2.0.0"
