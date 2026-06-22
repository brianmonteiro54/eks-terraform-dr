"""Ponto de entrada de linha de comando: python -m eks_importer ..."""
import sys

from .generator import generate_modular_eks_terraform


def main():
    # Por PADRÃO captura a VPC INTEIRA (todas as subnets/route tables/IGW/NAT/
    # TGW attachments/gateway endpoints). Para capturar só a rede que o cluster
    # usa (útil em DR reusando a VPC do destino), passe --cluster-subnets-only.
    OFF_FLAGS = {"--cluster-subnets-only", "--no-full-vpc"}
    full_vpc = not any(a in OFF_FLAGS for a in sys.argv)
    # --full-vpc continua aceito (agora é o padrão) para não quebrar scripts antigos.
    args = [a for a in sys.argv[1:] if a not in OFF_FLAGS and a != "--full-vpc"]
    if len(args) < 1:
        print("Uso: python -m eks_importer <nome-do-cluster> [regiao] [profile] [--cluster-subnets-only]")
        print("Exemplo: python -m eks_importer my-cluster sa-east-1 my-profile")
        print("  (PADRÃO) captura a VPC INTEIRA: todas as subnets/route tables/IGW/")
        print("           NAT/TGW attachments/gateway endpoints — ideal p/ recuperar")
        print("           a rede inteira na mesma conta.")
        print("  --cluster-subnets-only: captura SÓ a rede que o cluster usa")
        print("           (ideal p/ DR reusando a VPC do destino).")
        sys.exit(1)
    cluster_name = args[0]
    region = args[1] if len(args) > 1 else "sa-east-1"
    profile = args[2] if len(args) > 2 else None
    generate_modular_eks_terraform(cluster_name, region, profile, capture_full_vpc=full_vpc)


if __name__ == "__main__":
    main()
