"""Registro dos arquivos Terraform gerados (nome -> conteúdo HCL)."""
from .templates import (
    HCL_MAIN_TF, HCL_VARIABLES_TF, HCL_LOCALS_TF, HCL_NETWORK_TF,
    HCL_TRANSIT_GATEWAY_TF, HCL_IAM_TF, HCL_SECURITY_GROUPS_TF,
    HCL_LAUNCH_TEMPLATES_TF, HCL_CLUSTER_TF, HCL_NODEGROUPS_TF, HCL_FARGATE_TF,
    HCL_ACCESS_TF, HCL_ADDONS_TF, HCL_POD_IDENTITY_TF, HCL_OUTPUTS_TF,
)

TERRAFORM_FILES = {
    "main.tf": HCL_MAIN_TF,
    "variables.tf": HCL_VARIABLES_TF,
    "locals.tf": HCL_LOCALS_TF,
    "network.tf": HCL_NETWORK_TF,
    "transit_gateway.tf": HCL_TRANSIT_GATEWAY_TF,
    "iam.tf": HCL_IAM_TF,
    "security_groups.tf": HCL_SECURITY_GROUPS_TF,
    "launch_templates.tf": HCL_LAUNCH_TEMPLATES_TF,
    "cluster.tf": HCL_CLUSTER_TF,
    "nodegroups.tf": HCL_NODEGROUPS_TF,
    "fargate.tf": HCL_FARGATE_TF,
    "access.tf": HCL_ACCESS_TF,
    "addons.tf": HCL_ADDONS_TF,
    "pod_identity.tf": HCL_POD_IDENTITY_TF,
    "outputs.tf": HCL_OUTPUTS_TF,
}
