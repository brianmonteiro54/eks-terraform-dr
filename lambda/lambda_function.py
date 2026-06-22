"""Shim de deploy da Lambda.

Mantém o handler configurado como `lambda_function.lambda_handler` (convenção mais
comum) delegando ao pacote modular eks_exporter. Empacote este arquivo na RAIZ do
zip de deploy, ao lado da pasta eks_exporter/.
"""
from eks_exporter.handler import lambda_handler

__all__ = ["lambda_handler"]
