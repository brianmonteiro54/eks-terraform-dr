#!/usr/bin/env python3
"""Lançador fino: equivalente a `python -m eks_importer`.

Permite rodar `python3 run_eks_importer.py <cluster> [regiao] [profile] [flags]`
mantendo o pacote eks_importer/ ao lado deste arquivo.
"""
from eks_importer.__main__ import main

if __name__ == "__main__":
    main()
