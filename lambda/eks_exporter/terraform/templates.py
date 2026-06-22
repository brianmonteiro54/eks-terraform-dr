"""Templates HCL (.tf) que o gerador escreve no diretório de saída.

Cada constante é um arquivo Terraform da estratégia find-or-create. Strings puras,
sem dependências — extraídas verbatim do script original.
"""

# Estes são os arquivos .tf modulares que o script irá criar.
HCL_MAIN_TF = """
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.50.0"
    }
  }
}
provider "aws" {
  region = var.region
  # Mesmo profile usado pelos lookups (data.external). Vazio => cadeia padrão.
  profile = var.aws_profile != "" ? var.aws_profile : null
  default_tags {
    tags = {
      ManagedBy = "Terraform-Importer"
      Cluster   = var.cluster_name
    }
  }
}
"""
HCL_VARIABLES_TF = """
variable "region" {
  description = "AWS Region"
  type        = string
}
variable "cluster_name" {
  description = "Nome do cluster EKS"
  type        = string
}
variable "cluster_role_arn" {
  description = "IAM role ARN do cluster EKS"
  type        = string
}
variable "vpc_id" {
  description = "VPC ID onde o cluster será criado"
  type        = string
}
variable "subnet_ids" {
  description = "Lista da subnet IDs para o cluster EKS"
  type        = list(string)
}
variable "security_group_ids" {
  description = "Lista do security group IDs para o cluster EKS"
  type        = list(string)
  default     = []
}
variable "service_ipv4_cidr" {
  description = "Service CIDR block for Kubernetes services"
  type        = string
}
variable "cluster_version" {
  description = "Versão do Kubernetes para o cluster EKS"
  type        = string
}
variable "enabled_cluster_log_types" {
  description = "List of control plane logging types to enable"
  type        = list(string)
  default     = []
}
variable "support_type" {
  description = "Tipo de suporte para o cluster (STANDARD ou EXTENDED)"
  type        = string
  default     = "STANDARD"
}
variable "deletion_protection" {
  description = "Ative a proteção contra exclusão para o cluster."
  type        = bool
  default     = false
}
variable "cluster_tags" {
  description = "Additional tags para o cluster EKS"
  type        = map(string)
  default     = {}
}
# ---------- Endpoint de acesso do API server (refletem a origem) ----------
variable "endpoint_private_access" {
  description = "Habilita o endpoint privado do API server do EKS."
  type        = bool
  default     = true
}
variable "endpoint_public_access" {
  description = "Habilita o endpoint público do API server do EKS."
  type        = bool
  default     = false
}
variable "public_access_cidrs" {
  description = "CIDRs autorizados a acessar o endpoint público (quando habilitado). Vazio = padrão do EKS (0.0.0.0/0)."
  type        = list(string)
  default     = []
}
# ---------- Criptografia de secrets (KMS) ----------
variable "cluster_encryption_enabled" {
  description = "Se a ORIGEM usava criptografia de secrets com KMS. Definido pelo importer."
  type        = bool
  default     = false
}
variable "cluster_encryption_kms_key_arn" {
  description = "ARN da chave KMS do DESTINO para criptografar secrets. A chave da origem NÃO existe no destino; informe a do destino. Obrigatório se cluster_encryption_enabled = true."
  type        = string
  default     = ""
}
variable "authentication_mode" {
  description = "Modo de autenticação do cluster EKS. Valores válidos: CONFIG_MAP, API, API_AND_CONFIG_MAP"
  type        = string
}
variable "bootstrap_cluster_creator_admin_permissions" {
  description = "Se true, o criador do cluster receberá permissões de administrador automaticamente"
  type        = bool
}
# --- EKS Auto Mode ---
# IMPORTANTE: compute_config.enabled, elastic_load_balancing.enabled e
# block_storage.enabled precisam estar TODOS em true ou TODOS em false.
# Por isso usamos uma única flag para controlar os três simultaneamente.
variable "auto_mode_enabled" {
  description = "Habilita o EKS Auto Mode. compute_config, elastic_load_balancing e block_storage são habilitados/desabilitados sempre em conjunto."
  type        = bool
  default     = false
}
variable "auto_mode_node_pools" {
  description = "Node pools gerenciados pelo Auto Mode (ex: general-purpose, system). Usado apenas quando auto_mode_enabled = true."
  type        = list(string)
  default     = []
}
variable "auto_mode_node_role_arn" {
  description = "ARN da IAM Role atribuída às EC2 Managed Instances do Auto Mode. IMUTÁVEL após habilitar. Usado apenas quando auto_mode_enabled = true."
  type        = string
  default     = null
}
variable "nodegroups" {
  description = "Map of node groups to create"
  type = map(object({
    subnet_ids      = list(string)
    node_role_arn   = string
    scaling_min     = number
    scaling_max     = number
    scaling_desired = number
    ami_type        = string
    capacity_type   = string
    instance_types  = list(string)
    version         = string
    release_version = string
    labels          = map(string)
    tags            = map(string)
    disk_size       = optional(number)
    taints = optional(list(object({
      key    = string
      value  = optional(string)
      effect = string
    })), [])
    launch_template = object({
      id      = optional(string)
      name    = optional(string)
      version = string
    })
  }))
  default = {}
}
variable "fargate_profiles" {
  description = "Map of Fargate profiles to create"
  type = map(object({
    pod_execution_role_arn = string
    subnet_ids             = list(string)
    selectors = list(object({
      namespace = string
      labels    = optional(map(string), {})
    }))
    tags = optional(map(string), {})
  }))
  default = {}
}
variable "access_entries" {
  description = "Map of IAM access entries to create"
  type = map(object({
    principal_arn     = string
    kubernetes_groups = optional(list(string), [])
    type              = string
    user_name         = optional(string)
    policy_associations = optional(list(object({
      policy_arn = string
      access_scope = object({
        type       = string
        namespaces = optional(list(string), [])
      })
    })), [])
    tags = optional(map(string), {})
  }))
  default = {}
}
variable "addons" {
  description = "EKS add-ons configuration"
  type = map(object({
    addon_version            = string
    configuration_values     = optional(string, null)
    resolve_conflicts        = optional(string, "OVERWRITE")
    service_account_role_arn = optional(string, null)
    # NOVO: Suporte a Pod Identity Associations diretamente no add-on
    pod_identity_associations = optional(list(object({
      role_arn        = string
      service_account = string
    })), [])
    tags = optional(map(string), {})
  }))
  default = {}
}
variable "pod_identity_associations" {
  description = "EKS Pod Identity Associations (standalone, não vinculadas a add-ons)"
  type = map(object({
    namespace       = string
    service_account = string
    role_arn        = string
    tags            = optional(map(string), {})
  }))
  default = {}
}
# =====================================================================
# VARIÁVEIS ADICIONAIS — estratégia FIND-OR-CREATE (portabilidade entre contas)
# =====================================================================
variable "aws_profile" {
  description = "Profile do AWS CLI usado pelos lookups (data.external). Vazio = cadeia de credenciais padrão."
  type        = string
  default     = ""
}
variable "source_account_id" {
  description = "ID da conta AWS de ORIGEM (de onde o backup foi feito). Usado para reescrever ARNs de principals que não são recriados (ex.: users/federação em access entries)."
  type        = string
  default     = ""
}
# ---------- VPC ----------
variable "vpc_cidr" {
  description = "CIDR primário da VPC de origem. É a CHAVE de busca: se já existir VPC com este CIDR no destino, ela é reutilizada."
  type        = string
}
variable "vpc_name" {
  description = "Nome (tag Name) da VPC, usado apenas quando a VPC é criada do zero."
  type        = string
  default     = "eks-vpc"
}
variable "vpc_instance_tenancy" {
  description = "instance_tenancy da VPC (default/dedicated)."
  type        = string
  default     = "default"
}
variable "vpc_enable_dns_support" {
  description = "Habilita DNS support na VPC criada."
  type        = bool
  default     = true
}
variable "vpc_enable_dns_hostnames" {
  description = "Habilita DNS hostnames na VPC criada."
  type        = bool
  default     = true
}
variable "vpc_tags" {
  description = "Tags da VPC e recursos de rede criados."
  type        = map(string)
  default     = {}
}
variable "vpc_secondary_cidrs" {
  description = "CIDRs secundários associados à VPC (criados apenas quando a VPC é nova)."
  type        = list(string)
  default     = []
}
variable "create_internet_gateway" {
  description = "Se true, cria um Internet Gateway quando a VPC é criada do zero."
  type        = bool
  default     = true
}
variable "create_nat_gateways" {
  description = "Se true, recria os NAT Gateways da origem (fiel: 1 por 1, cada um na sua subnet pública) quando a VPC é nova. Se false, não cria nenhum (economiza custo em DR). Gera custo por NAT."
  type        = bool
  default     = false
}
variable "disable_resource_reuse" {
  description = <<-EOT
    Desliga o find-or-create: quando true, a ferramenta NÃO reaproveita nenhum
    recurso de base existente; ela CRIA e PASSA A GERENCIAR todos eles (VPC,
    subnets, route tables, IGW, NAT, IAM roles/policies/users, SGs, key pairs,
    launch templates, instance profiles).
    Use true quando o destino está LIMPO (ex.: recuperação na MESMA conta depois
    de apagar a base, ou um destino novo vazio). Isso torna o `terraform apply`
    IDEMPOTENTE: como o Terraform sempre gerencia esses recursos, um segundo
    apply não tenta "encontrá-los" e destruí-los.
    Deixe false (padrão) no DR entre contas quando a base (VPC, roles, etc.) já
    existe no destino e deve ser REAPROVEITADA. Atenção: com true, se algum
    desses recursos JÁ existir no destino, o apply falha por conflito de nome
    (ex.: EntityAlreadyExists) — use só em destino limpo.
  EOT
  type    = bool
  default = false
}
# ---------- Subnets ----------
# Mapa keyed pelo ID da subnet de ORIGEM (ex.: subnet-0abc...).
variable "subnets" {
  description = "Subnets da origem (keyed pelo subnet-id de origem). Find-or-create por (vpc-id + cidr-block)."
  type = map(object({
    cidr_block              = string
    availability_zone       = string
    map_public_ip_on_launch = bool
    is_public               = bool
    tags                    = map(string)
  }))
  default = {}
}
# ---------- Route tables / rotas / associações ----------
# Criadas apenas quando a VPC é nova (keyed pelo route-table-id de origem).
variable "route_tables" {
  description = "Route tables da origem (keyed pelo route-table-id de origem). Criadas apenas quando a VPC é nova."
  type = map(object({
    tags = map(string)
  }))
  default = {}
}
variable "routes" {
  description = "Rotas a recriar quando a VPC é nova. Cobre TODOS os alvos: igw|nat|egress_only_igw (recriados pela stack) e tgw|peering|vgw|vpce|eni|carrier|core_network (alvos externos, recriados com o ID literal da origem). Destino pode ser cidr, ipv6 ou prefix-list."
  type = list(object({
    key                         = string
    route_table_source_id       = string
    destination_cidr_block      = optional(string, "")
    destination_ipv6_cidr_block = optional(string, "")
    destination_prefix_list_id  = optional(string, "")
    target_kind                 = string
    target_id                   = optional(string, "")
  }))
  default = []
}
variable "recreate_external_routes" {
  description = "Recria rotas E o TGW attachment cujo alvo é EXTERNO/persistente (tgw, peering, vgw, gateway endpoint, eni, carrier, core network) usando o ID LITERAL capturado da origem. Use true para RECUPERACAO na MESMA conta (esses alvos ainda existem). Use false para DR em OUTRA conta (esses IDs nao existiriam la e o apply falharia) — exceto gateway endpoints S3/DynamoDB, que sempre funcionam pois o service e global da AWS. Excecao: se o TGW for compartilhado com a conta de destino via AWS RAM, pode manter true."
  type    = bool
  default = true
}
variable "route_table_associations" {
  description = "Associações subnet->route-table a recriar quando a VPC é nova."
  type = list(object({
    key                   = string
    subnet_source_id      = string
    route_table_source_id = string
  }))
  default = []
}
variable "transit_gateway_attachments" {
  description = "Attachments da VPC a um Transit Gateway, recriados quando a VPC é nova (necessários para as rotas '-> tgw-xxx' funcionarem). O transit_gateway_id é a CHAVE de origem; o ID efetivo no destino é resolvido pelo find-or-create (transit_gateways): RAM compartilhado, mesmo Name tag, ou TGW recém-criado. As subnets são remapeadas origem->destino (capturadas por padrão, junto com a VPC inteira)."
  type = map(object({
    transit_gateway_id     = string
    subnet_source_ids      = list(string)
    dns_support            = bool
    ipv6_support           = bool
    appliance_mode_support = bool
    tags                   = map(string)
  }))
  default = {}
}
variable "gateway_endpoints" {
  description = "VPC Gateway Endpoints (S3/DynamoDB) a recriar quando a VPC é nova. O próprio endpoint recria as rotas por prefix-list nas route tables associadas. service_name embute a região (mesma região do destino)."
  type = map(object({
    service_name           = string
    route_table_source_ids = list(string)
    policy                 = string
    tags                   = map(string)
  }))
  default = {}
}
variable "nat_gateways" {
  description = "NAT Gateways da origem (keyed pelo nat-id de origem), recriados FIEL: zonal = 1 por subnet pública (com EIP); regional (availability_mode=regional) = 1 multi-AZ na VPC, em auto mode (a AWS gerencia EIPs/AZs, sem subnet). Cada rota privada aponta para o NAT correto (via nat-id). Criados só quando a VPC é nova e create_nat_gateways = true."
  type = map(object({
    subnet_source_id  = string
    connectivity_type = optional(string, "public")
    availability_mode = optional(string, "zonal")
    tags              = map(string)
  }))
  default = {}
}
variable "interface_endpoints" {
  description = "VPC Interface Endpoints (ECR, STS, CloudWatch Logs, EC2, etc.) — essenciais em VPC privada para o cluster puxar imagens do ECR, assumir roles e mandar logs sem sair para a internet. Recriados FIEL à origem (mesmos ip_address_type e dns_options) quando a VPC é nova; subnets e SGs são remapeados para o destino (os SGs entram no find-or-create). service_name embute a região (mesma região do destino)."
  type = map(object({
    service_name              = string
    subnet_source_ids         = list(string)
    security_group_source_ids = list(string)
    private_dns_enabled       = bool
    ip_address_type           = optional(string, "")
    dns_record_ip_type        = optional(string, "")
    private_dns_only_for_inbound_resolver_endpoint = optional(bool, false)
    policy                    = string
    tags                      = map(string)
  }))
  default = {}
}
variable "dhcp_options" {
  description = "Conjunto de opções DHCP CUSTOMIZADO da VPC (DNS on-prem, NTP, NetBIOS), keyed pelo dopt-id de origem. Recriado fiel e associado à VPC nova. Só vem preenchido quando a origem usa um DHCP customizado (não o default AmazonProvidedDNS); senão a VPC nova usa o default da região. Vazio = nada a recriar."
  type = map(object({
    domain_name          = optional(string, "")
    domain_name_servers  = optional(list(string), [])
    ntp_servers          = optional(list(string), [])
    netbios_name_servers = optional(list(string), [])
    netbios_node_type    = optional(string, "")
    tags                 = map(string)
  }))
  default = {}
}
# ---------- IAM roles ----------
# Mapa keyed pelo NOME da role (chave natural cross-account).
variable "iam_roles" {
  description = "IAM roles referenciadas pelo cluster/nodegroups/fargate/auto-mode (keyed pelo nome). Find-or-create por nome."
  type = map(object({
    source_arn           = string
    path                 = string
    description          = string
    assume_role_policy   = string
    max_session_duration = number
    permissions_boundary = string
    managed_policy_arns  = list(string)
    inline_policies      = map(string)
    tags                 = map(string)
  }))
  default = {}
}
# ---------- Policies customer-managed ----------
# Mapa keyed pelo NOME da policy. Recriadas (find-or-create por nome) no destino,
# pois as customer-managed da origem não existem em outra conta. As policies
# gerenciadas pela AWS (arn:aws:iam::aws:policy/...) NÃO entram aqui.
variable "customer_managed_policies" {
  description = "Policies IAM customer-managed referenciadas por roles (keyed pelo nome). Find-or-create por nome."
  type = map(object({
    source_arn  = string
    path        = string
    description = string
    document    = string
  }))
  default = {}
}
# ---------- Users IAM (referenciados por access entries) ----------
# Mapa keyed pelo NOME do user. Recriados (find-or-create por nome) como users
# VAZIOS (sem credenciais) para que o principal do access entry exista no destino.
variable "iam_users" {
  description = "Users IAM referenciados por access entries (keyed pelo nome). Find-or-create por nome; criados sem credenciais."
  type = map(object({
    path = string
  }))
  default = {}
}
# ---------- Security groups adicionais ----------
# Mapa keyed pelo ID do SG de ORIGEM (ex.: sg-0abc...).
variable "security_groups" {
  description = "Security groups ADICIONAIS do cluster (keyed pelo sg-id de origem). Find-or-create por (vpc-id + group-name)."
  type = map(object({
    name        = string
    description = string
    tags        = map(string)
  }))
  default = {}
}
variable "sg_ingress_rules" {
  description = "Regras de ingress (uma por alvo). Strings vazias viram null no recurso."
  type = list(object({
    key                     = string
    sg_source_id            = string
    ip_protocol             = string
    from_port               = optional(number)
    to_port                 = optional(number)
    cidr_ipv4               = string
    cidr_ipv6               = string
    prefix_list_id          = string
    referenced_sg_source_id = string
    description             = string
  }))
  default = []
}
variable "sg_egress_rules" {
  description = "Regras de egress (uma por alvo). Strings vazias viram null no recurso."
  type = list(object({
    key                     = string
    sg_source_id            = string
    ip_protocol             = string
    from_port               = optional(number)
    to_port                 = optional(number)
    cidr_ipv4               = string
    cidr_ipv6               = string
    prefix_list_id          = string
    referenced_sg_source_id = string
    description             = string
  }))
  default = []
}
variable "cluster_sg_ingress_rules" {
  description = "Regras de ingress ADICIONADAS manualmente ao Cluster SG do EKS (recriadas no Cluster SG do cluster de destino). Token __CLUSTER_SG__ no referenced_sg_source_id aponta para o Cluster SG novo."
  type = list(object({
    key                     = string
    sg_source_id            = string
    ip_protocol             = string
    from_port               = optional(number)
    to_port                 = optional(number)
    cidr_ipv4               = string
    cidr_ipv6               = string
    prefix_list_id          = string
    referenced_sg_source_id = string
    description             = string
  }))
  default = []
}
variable "cluster_sg_egress_rules" {
  description = "Regras de egress ADICIONADAS manualmente ao Cluster SG do EKS (recriadas no Cluster SG do cluster de destino)."
  type = list(object({
    key                     = string
    sg_source_id            = string
    ip_protocol             = string
    from_port               = optional(number)
    to_port                 = optional(number)
    cidr_ipv4               = string
    cidr_ipv6               = string
    prefix_list_id          = string
    referenced_sg_source_id = string
    description             = string
  }))
  default = []
}
# ---------- Launch Templates (recriação automática) ----------
variable "source_cluster_security_group_id" {
  description = "ID do Cluster SG da ORIGEM (gerenciado pelo EKS). Usado para remapear referências a ele dentro de launch templates e regras de SG para o Cluster SG do cluster de destino."
  type        = string
  default     = ""
}
variable "instance_profiles" {
  description = "Instance profiles usados pelos launch templates (recriados find-or-create; a role é capturada em iam_roles)."
  type = map(object({
    source_role_arn = string
  }))
  default = {}
}
# ---------- Key pairs EC2 ----------
# Mapa keyed pelo NOME do key pair. Recriados (find-or-create por nome) no destino
# com a MESMA chave pública da origem — assim a chave privada que você já baixou
# continua válida. A privada nunca passa pela ferramenta.
variable "key_pairs" {
  description = "Key pairs EC2 referenciados por launch templates/nodegroups (keyed pelo nome). Find-or-create por nome, recriando a chave pública da origem."
  type = map(object({
    public_key = string
    key_type   = string
    tags       = map(string)
  }))
  default = {}
}
variable "launch_templates" {
  description = "Launch templates referenciados por nodegroups (recriados find-or-create por nome). O user-data é omitido de propósito: o EKS injeta o bootstrap do cluster novo."
  type = map(object({
    name                          = string
    image_id                      = string
    instance_type                 = string
    key_name                      = string
    ebs_optimized                 = string
    monitoring_enabled            = bool
    vpc_security_group_source_ids = list(string)
    iam_instance_profile_name     = string
    block_device_mappings = list(object({
      device_name           = string
      volume_size           = optional(number)
      volume_type           = string
      iops                  = optional(number)
      throughput            = optional(number)
      encrypted             = string
      delete_on_termination = string
    }))
    metadata_options = object({
      http_endpoint               = string
      http_tokens                 = string
      http_put_response_hop_limit = optional(number)
      instance_metadata_tags      = string
    })
    tag_specifications = list(object({
      resource_type = string
      tags          = map(string)
    }))
  }))
  default = {}
}
# ---------- Transit Gateways (replicação cross-account) ----------
# Mapa keyed pelo ID do TGW de ORIGEM (ex.: tgw-0abc...). Só é preenchido quando
# há rotas/attachment para TGW E recreate_external_routes = true. Find-or-create
# em 3 estratégias: (1) mesmo ID visível via RAM, (2) mesmo Name tag na conta de
# destino, (3) cria um TGW novo com a MESMA configuração da origem.
variable "transit_gateways" {
  description = "Transit Gateways referenciados por rotas/attachment (keyed pelo tgw-id de origem). Find-or-create: RAM compartilhado -> mesmo ID; mesmo Name tag no destino -> ID existente; senão cria um TGW novo idêntico ao da origem. As route tables CUSTOMIZADAS e suas rotas estáticas são recriadas junto."
  type = map(object({
    name                            = string
    description                     = optional(string, "")
    amazon_side_asn                 = optional(number, 64512)
    auto_accept_shared_attachments  = optional(string, "disable")
    default_route_table_association = optional(string, "enable")
    default_route_table_propagation = optional(string, "enable")
    dns_support                     = optional(string, "enable")
    vpn_ecmp_support                = optional(string, "enable")
    multicast_support               = optional(string, "disable")
    tags                            = optional(map(string), {})
    route_tables = optional(map(object({
      tags = optional(map(string), {})
      static_routes = optional(list(object({
        cidr      = string
        blackhole = optional(bool, false)
      })), [])
    })), {})
  }))
  default = {}
}
"""
HCL_CLUSTER_TF = """
resource "aws_eks_cluster" "main" {
  name = var.cluster_name
  # role_arn vem da tabela de tradução (ARN de origem -> ARN no destino).
  role_arn = local.cluster_role_arn
  version  = var.cluster_version
  # Em clusters Auto Mode, os add-ons de rede (VPC CNI, CoreDNS, kube-proxy)
  # são gerenciados off-cluster pelo próprio EKS, então NÃO devem ser
  # bootstrapped pelo fluxo clássico. Quando Auto Mode está desabilitado,
  # deixamos no default do provider (null).
  bootstrap_self_managed_addons = var.auto_mode_enabled ? false : null
  vpc_config {
    # subnets e SGs vêm das tabelas de tradução (origem -> destino).
    subnet_ids = local.cluster_subnet_ids
    # IMPORTANTE: security_group_ids são ADICIONAIS ao Cluster Security Group
    # O EKS cria automaticamente um "Cluster Security Group" que não pode ser especificado aqui
    # O Cluster Security Group é gerenciado pelo EKS e estará disponível em:
    # aws_eks_cluster.main.vpc_config[0].cluster_security_group_id (como output)
    security_group_ids      = local.cluster_security_group_ids
    # Refletem a configuração da ORIGEM (não mais valores fixos).
    endpoint_private_access = var.endpoint_private_access
    endpoint_public_access  = var.endpoint_public_access
    # A API do EKS REJEITA public_access_cidrs quando o endpoint público está
    # desligado (a AWS retorna 0.0.0.0/0 mesmo nesse caso). Só setamos os CIDRs
    # quando o acesso público está habilitado.
    public_access_cidrs = (
      var.endpoint_public_access && length(var.public_access_cidrs) > 0
      ? var.public_access_cidrs
      : null
    )
  }
  # ============================================================
  # EKS Auto Mode
  # Os três blocos abaixo (compute_config, elastic_load_balancing
  # e block_storage) precisam ter 'enabled' com o MESMO valor.
  # Todos true  -> Auto Mode ligado
  # Todos false -> cluster clássico
  # Setar apenas um deles faz o provider falhar.
  # ============================================================
  compute_config {
    enabled    = var.auto_mode_enabled
    node_pools = var.auto_mode_enabled ? var.auto_mode_node_pools : null
    # A AWS REJEITA node_role_arn setado com node_pools vazio:
    # "When Compute Config nodeRoleArn is not null or empty, nodePool value(s)
    # must be provided" (InvalidParameterException). Então só setamos a role
    # quando há ao menos um node pool; sem node pools (Auto Mode só com pools
    # custom via API do k8s), node_role_arn fica null.
    node_role_arn = (
      var.auto_mode_enabled && length(var.auto_mode_node_pools) > 0
      ? local.auto_mode_node_role_arn : null
    )
  }
  kubernetes_network_config {
    service_ipv4_cidr = var.service_ipv4_cidr
    ip_family         = "ipv4"
    elastic_load_balancing {
      enabled = var.auto_mode_enabled
    }
  }
  storage_config {
    block_storage {
      enabled = var.auto_mode_enabled
    }
  }
  enabled_cluster_log_types = var.enabled_cluster_log_types
  access_config {
    authentication_mode                         = var.authentication_mode
    bootstrap_cluster_creator_admin_permissions = var.bootstrap_cluster_creator_admin_permissions
  }
  upgrade_policy {
    support_type = var.support_type
  }
  deletion_protection = var.deletion_protection
  tags                = var.cluster_tags
  # Criptografia de secrets com KMS. A chave da ORIGEM não existe no destino,
  # então o ARN da chave do DESTINO é fornecido por variável. Só é emitido se
  # a origem usava encryption_config E você informar a chave do destino.
  dynamic "encryption_config" {
    for_each = var.cluster_encryption_enabled && var.cluster_encryption_kms_key_arn != "" ? [1] : []
    content {
      resources = ["secrets"]
      provider {
        key_arn = var.cluster_encryption_kms_key_arn
      }
    }
  }
  # Auto Mode não suporta autenticação CONFIG_MAP-only; exige API ou API_AND_CONFIG_MAP.
  lifecycle {
    precondition {
      condition     = !var.auto_mode_enabled || contains(["API", "API_AND_CONFIG_MAP"], var.authentication_mode)
      error_message = "EKS Auto Mode exige authentication_mode = API ou API_AND_CONFIG_MAP."
    }
    precondition {
      condition     = !var.cluster_encryption_enabled || var.cluster_encryption_kms_key_arn != ""
      error_message = "A origem usava criptografia de secrets (KMS), mas cluster_encryption_kms_key_arn está vazio. Informe o ARN de uma chave KMS da conta de DESTINO (a chave da origem não existe aqui) ou defina cluster_encryption_enabled = false para abrir mão da criptografia."
    }
  }
  # Garante que as policies da IAM role e o roteamento das subnets estejam
  # prontos ANTES de criar o cluster (find-or-create).
  depends_on = [
    aws_iam_role.this,
    aws_iam_role_policy_attachment.this,
    aws_iam_role_policy.this,
    aws_route_table_association.this,
  ]
}
"""
HCL_NODEGROUPS_TF = """
# Quando um nodegroup usa launch template, a API do EKS PROÍBE definir certos
# campos no próprio nodegroup (eles passam a vir do LT):
#   - SEMPRE que há LT: instance_types e disk_size não podem ser definidos;
#   - se o LT usa AMI custom (tem image_id): ami_type, version e release_version
#     também não podem ser definidos.
# Estes mapas pré-calculam essas condições por nodegroup.
locals {
  ng_uses_lt = {
    for k, ng in var.nodegroups : k => ng.launch_template.id != null
  }
  ng_lt_custom_ami = {
    for k, ng in var.nodegroups : k => (
      ng.launch_template.id != null
      && try(var.launch_templates[ng.launch_template.id].image_id, "") != ""
    )
  }
}
resource "aws_eks_node_group" "this" {
  for_each = var.nodegroups
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = each.key
  # Remapeados da origem para o destino via tabelas de tradução.
  node_role_arn = local.iam_role_arn_by_source_arn[each.value.node_role_arn]
  subnet_ids    = [for s in each.value.subnet_ids : local.subnet_id_by_source[s]]
  # Campos que a API do EKS proíbe quando há launch template (ver locals acima).
  ami_type        = local.ng_lt_custom_ami[each.key] ? null : each.value.ami_type
  capacity_type   = each.value.capacity_type
  instance_types  = local.ng_uses_lt[each.key] ? null : each.value.instance_types
  version         = local.ng_lt_custom_ami[each.key] ? null : each.value.version
  release_version = local.ng_lt_custom_ami[each.key] ? null : each.value.release_version
  labels = each.value.labels
  tags   = each.value.tags
  # disk_size também não pode ser definido quando há launch template.
  disk_size = local.ng_uses_lt[each.key] ? null : each.value.disk_size
  scaling_config {
    min_size     = each.value.scaling_min
    max_size     = each.value.scaling_max
    desired_size = each.value.scaling_desired
  }
  # Taints da origem (controlam o scheduling dos pods).
  dynamic "taint" {
    for_each = each.value.taints
    content {
      key    = taint.value.key
      value  = try(taint.value.value, null)
      effect = taint.value.effect
    }
  }
  update_config {
    max_unavailable = 1
  }
  dynamic "launch_template" {
    # Referencia o LT RECRIADO no destino (id/versão efetivos), não o da origem.
    for_each = each.value.launch_template.id != null ? [each.value.launch_template] : []
    content {
      id      = local.launch_template_id_by_source[each.value.launch_template.id]
      version = local.launch_template_version_by_source[each.value.launch_template.id]
    }
  }
  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
  depends_on = [
    aws_eks_cluster.main
  ]
}
"""
HCL_FARGATE_TF = """
resource "aws_eks_fargate_profile" "this" {
  for_each = var.fargate_profiles
  cluster_name         = aws_eks_cluster.main.name
  fargate_profile_name = each.key
  # Remapeados da origem para o destino via tabelas de tradução.
  pod_execution_role_arn = local.iam_role_arn_by_source_arn[each.value.pod_execution_role_arn]
  subnet_ids             = [for s in each.value.subnet_ids : local.subnet_id_by_source[s]]
  dynamic "selector" {
    for_each = each.value.selectors
    content {
      namespace = selector.value.namespace
      labels    = try(selector.value.labels, {})
    }
  }
  tags = each.value.tags
  depends_on = [
    aws_eks_cluster.main
  ]
}
"""
HCL_ACCESS_TF = """
resource "aws_eks_access_entry" "this" {
  for_each = var.access_entries
  cluster_name      = aws_eks_cluster.main.name
  principal_arn     = local.translated_principal_arn[each.value.principal_arn]
  kubernetes_groups = try(each.value.kubernetes_groups, [])
  type              = each.value.type
  user_name         = try(each.value.user_name, null)
  tags              = try(each.value.tags, {})
  depends_on = [
    aws_eks_cluster.main
  ]
}
# Cria associações de políticas para cada entrada que possui políticas
locals {
  # Expande as associações de políticas em uma estrutura plana
  policy_associations = flatten([
    for entry_key, entry_val in var.access_entries : [
      for idx, policy in try(entry_val.policy_associations, []) : {
        entry_key  = entry_key
        policy_key = "${entry_key}_${idx}"
        principal_arn = local.translated_principal_arn[entry_val.principal_arn]
        policy_arn    = policy.policy_arn
        access_scope  = policy.access_scope
      }
    ]
  ])
  
  # Converte para um map para usar com for_each
  policy_associations_map = {
    for assoc in local.policy_associations :
    assoc.policy_key => assoc
  }
}
resource "aws_eks_access_policy_association" "this" {
  for_each = local.policy_associations_map
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value.principal_arn
  policy_arn    = each.value.policy_arn
  access_scope {
    type       = each.value.access_scope.type
    namespaces = try(each.value.access_scope.namespaces, [])
  }
  depends_on = [
    aws_eks_access_entry.this
  ]
}
"""
# ATUALIZADO: Template de add-ons com suporte a pod_identity_association
HCL_ADDONS_TF = """
resource "aws_eks_addon" "this" {
  for_each = var.addons
  cluster_name                = aws_eks_cluster.main.name
  addon_name                  = each.key
  addon_version               = each.value.addon_version
  configuration_values        = each.value.configuration_values
  # A AWS aceita só NONE/OVERWRITE em on_create (PRESERVE é exclusivo de on_update).
  # Se a origem trouxe PRESERVE, usamos OVERWRITE na criação para não ser rejeitado.
  resolve_conflicts_on_create = each.value.resolve_conflicts == "PRESERVE" ? "OVERWRITE" : each.value.resolve_conflicts
  resolve_conflicts_on_update = each.value.resolve_conflicts
  
  # IRSA (legado) - usado apenas se NÃO houver pod_identity_associations.
  # Remapeado da origem para o destino quando presente.
  service_account_role_arn = length(each.value.pod_identity_associations) == 0 && each.value.service_account_role_arn != null ? local.translated_principal_arn[each.value.service_account_role_arn] : null
  # NOVO: Pod Identity Associations diretamente no add-on
  dynamic "pod_identity_association" {
    for_each = each.value.pod_identity_associations
    content {
      role_arn        = local.translated_principal_arn[pod_identity_association.value.role_arn]
      service_account = pod_identity_association.value.service_account
    }
  }
  tags = each.value.tags
  
  depends_on = [
    aws_eks_cluster.main,
    aws_eks_node_group.this # Garante que os nodegroups existam antes dos addons
  ]
}
"""
# ATUALIZADO: Pod Identity standalone (não vinculadas a add-ons)
HCL_POD_IDENTITY_TF = """
# Pod Identity Associations standalone (não vinculadas a add-ons)
# NOTA: Associações de add-ons são gerenciadas diretamente no recurso aws_eks_addon
resource "aws_eks_pod_identity_association" "this" {
  for_each = var.pod_identity_associations
  cluster_name    = aws_eks_cluster.main.name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  # Remapeado da origem para o destino (find-or-create da role, ou reescrita do account-id).
  role_arn        = local.translated_principal_arn[each.value.role_arn]
  # tags = {} (vazio) causa drift perpétuo no aws_eks_pod_identity_association
  # (bug conhecido do provider). Passamos null quando não há tags.
  tags = length(each.value.tags) > 0 ? each.value.tags : null
  depends_on = [
    aws_eks_cluster.main,
    aws_eks_addon.this # Requer eks-pod-identity-agent addon
  ]
}
"""
HCL_OUTPUTS_TF = """
output "cluster_name" {
  description = "Nome do cluster EKS"
  value       = aws_eks_cluster.main.name
}
output "cluster_endpoint" {
  description = "Endpoint para o servidor de API do cluster EKS"
  value       = aws_eks_cluster.main.endpoint
}
output "cluster_arn" {
  description = "ARN do cluster EKS"
  value       = aws_eks_cluster.main.arn
}
output "cluster_security_group_id" {
  description = "Security group ID anexado ao cluster EKS"
  value       = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}
output "auto_mode_enabled" {
  description = "Indica se o EKS Auto Mode está habilitado no cluster"
  value       = aws_eks_cluster.main.compute_config[0].enabled
}
output "nodegroup_ids" {
  description = "Map do node group IDs"
  value       = { for k, v in aws_eks_node_group.this : k => v.id }
}
output "addon_pod_identity_associations" {
  description = "Pod Identity Associations configuradas nos add-ons"
  value = {
    for addon_name, addon in aws_eks_addon.this :
    addon_name => addon.pod_identity_association
  }
}
"""
# =====================================================================
# NOVOS arquivos .tf da estratégia FIND-OR-CREATE (portabilidade entre contas)
# =====================================================================
HCL_NETWORK_TF = """
# =====================================================================
# REDE — estratégia FIND-OR-CREATE
#
# Princípio: na conta de DESTINO, para cada recurso consultamos primeiro
# (via data.external -> scripts/aws_lookup.py, que usa o AWS CLI):
#   • Existe? -> reutiliza o ID existente.
#   • Não existe? -> cria idêntico ao original.
#
# Premissa importante: se a VPC com o mesmo CIDR JÁ EXISTE no destino,
# assumimos que a malha de rede dela (route tables, IGW, NAT) também já
# existe — então NÃO recriamos route tables/rotas; apenas reutilizamos a
# VPC e procuramos/garantimos subnets e security groups. Quando a VPC NÃO
# existe, construímos tudo do zero.
# =====================================================================
# --------------------------------------------------------------------
# VPC
# --------------------------------------------------------------------
data "external" "vpc_lookup" {
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "vpc"
    exclude_value = var.cluster_name
    region  = var.region
    cidr    = var.vpc_cidr
    profile = var.aws_profile
  }
}
locals {
  # Find-or-create: a VPC é "encontrada" (reusada) só se o lookup achou E o
  # reuso não foi desligado. Com disable_resource_reuse=true, vpc_found=false,
  # então a VPC (e em cascata subnets, IGW, NAT, route tables e SGs, todos
  # condicionados a vpc_found) é CRIADA e GERENCIADA — apply idempotente.
  vpc_found = var.disable_resource_reuse ? false : (data.external.vpc_lookup.result.id != "")
}
resource "aws_vpc" "this" {
  count = local.vpc_found ? 0 : 1
  cidr_block           = var.vpc_cidr
  instance_tenancy     = var.vpc_instance_tenancy
  enable_dns_support   = var.vpc_enable_dns_support
  enable_dns_hostnames = var.vpc_enable_dns_hostnames
  tags = merge(var.vpc_tags, { Name = var.vpc_name }, local.stack_marker_tags)
}
# CIDRs secundários (apenas quando criamos a VPC do zero)
resource "aws_vpc_ipv4_cidr_block_association" "secondary" {
  for_each = local.vpc_found ? toset([]) : toset(var.vpc_secondary_cidrs)
  vpc_id     = aws_vpc.this[0].id
  cidr_block = each.value
}
# DHCP options set customizado (DNS on-prem, NTP, NetBIOS) — recriado e associado
# à VPC nova, fiel à origem. Só existe quando a origem usa um conjunto customizado
# (não o default AmazonProvidedDNS). Pulado quando a VPC do destino é reusada.
resource "aws_vpc_dhcp_options" "this" {
  for_each = local.vpc_found ? {} : var.dhcp_options
  domain_name          = each.value.domain_name != "" ? each.value.domain_name : null
  domain_name_servers  = length(each.value.domain_name_servers) > 0 ? each.value.domain_name_servers : null
  ntp_servers          = length(each.value.ntp_servers) > 0 ? each.value.ntp_servers : null
  netbios_name_servers = length(each.value.netbios_name_servers) > 0 ? each.value.netbios_name_servers : null
  netbios_node_type    = each.value.netbios_node_type != "" ? each.value.netbios_node_type : null
  tags = merge(each.value.tags, local.stack_marker_tags)
}
resource "aws_vpc_dhcp_options_association" "this" {
  for_each = local.vpc_found ? {} : var.dhcp_options
  vpc_id          = local.vpc_id
  dhcp_options_id = aws_vpc_dhcp_options.this[each.key].id
}
locals {
  # ID efetivo da VPC: o encontrado, ou o recém-criado.
  vpc_id = local.vpc_found ? data.external.vpc_lookup.result.id : aws_vpc.this[0].id
}
# --------------------------------------------------------------------
# Internet Gateway (só consultamos quando a VPC já existe; o lookup
# depende do vpc_id, que só é conhecido em plan quando a VPC existe)
# --------------------------------------------------------------------
data "external" "igw_lookup" {
  count   = local.vpc_found ? 1 : 0
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "internet_gateway"
    exclude_value = var.cluster_name
    region  = var.region
    vpc_id  = local.vpc_id
    profile = var.aws_profile
  }
}
locals {
  igw_found = local.vpc_found ? (data.external.igw_lookup[0].result.id != "") : false
}
resource "aws_internet_gateway" "this" {
  count  = (var.create_internet_gateway && !local.vpc_found) ? 1 : 0
  vpc_id = local.vpc_id
  tags = merge(var.vpc_tags, { Name = "${var.vpc_name}-igw" })
}
locals {
  igw_id = local.igw_found ? data.external.igw_lookup[0].result.id : (
    length(aws_internet_gateway.this) > 0 ? aws_internet_gateway.this[0].id : ""
  )
}
# --------------------------------------------------------------------
# Subnets — find-or-create por (vpc-id + cidr-block)
# A consulta só roda quando a VPC já existe (senão, tudo é criado novo).
# --------------------------------------------------------------------
data "external" "subnet_lookup" {
  for_each = local.vpc_found ? var.subnets : {}
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "subnet"
    exclude_value = var.cluster_name
    region  = var.region
    vpc_id  = local.vpc_id
    cidr    = each.value.cidr_block
    profile = var.aws_profile
  }
}
locals {
  subnet_found = {
    for k, v in var.subnets : k => (
      local.vpc_found ? try(data.external.subnet_lookup[k].result.id, "") != "" : false
    )
  }
}
resource "aws_subnet" "this" {
  for_each = { for k, v in var.subnets : k => v if !local.subnet_found[k] }
  vpc_id                  = local.vpc_id
  cidr_block              = each.value.cidr_block
  availability_zone       = each.value.availability_zone
  map_public_ip_on_launch = each.value.map_public_ip_on_launch
  tags = merge(each.value.tags, local.stack_marker_tags)
}
locals {
  # Mapa: ID de subnet na conta de ORIGEM -> ID na conta de DESTINO.
  # É a "tabela de tradução" usada por cluster, nodegroups e fargate.
  subnet_id_by_source = {
    for src_id, cfg in var.subnets : src_id => try(
      # 1) se a subnet é gerenciada por nós, usa o id dela;
      aws_subnet.this[src_id].id,
      # 2) senão, se foi encontrada no destino, usa o id do lookup;
      data.external.subnet_lookup[src_id].result.id,
      # 3) fallback "" — só ocorre transitoriamente durante `terraform import`
      #    (quando há subnets no tfvars ainda não criadas); no apply seguinte
      #    o ramo (1) resolve. Evita erro "Invalid index" no import.
      ""
    )
  }
}
# --------------------------------------------------------------------
# Route tables, rotas e associações — criados apenas quando a VPC é nova
# --------------------------------------------------------------------
resource "aws_route_table" "this" {
  for_each = local.vpc_found ? {} : var.route_tables
  vpc_id = local.vpc_id
  tags   = each.value.tags
}
# Rotas (igw/nat/egress-only + alvos externos) são recriadas no recurso
# unificado aws_route.all, mais abaixo (depende do NAT/egress-only IGW).
# Associações subnet -> route table
resource "aws_route_table_association" "this" {
  for_each = {
    for a in var.route_table_associations : a.key => a
    if !local.vpc_found
  }
  subnet_id      = local.subnet_id_by_source[each.value.subnet_source_id]
  route_table_id = aws_route_table.this[each.value.route_table_source_id].id
}
# --------------------------------------------------------------------
# NAT Gateways — recriados FIEL à origem (1 por 1, na mesma subnet pública).
# Se a origem tem 1 NAT por AZ, recria 1 por AZ (HA preservado). Controlado por
# create_nat_gateways (false = nenhum, p/ economizar em DR). Cada rota privada
# aponta para o NAT correto (mapeado pelo nat-id de origem em route_target_id).
# --------------------------------------------------------------------
locals {
  # NATs a recriar quando a VPC é nova e NAT habilitado:
  #  • regionais: sempre (não dependem de subnet — usam a VPC inteira);
  #  • zonais: só se a subnet pública dele foi capturada (evita índice inválido).
  nat_gateways_to_create = (!local.vpc_found && var.create_nat_gateways) ? {
    for k, v in var.nat_gateways : k => v
    if v.availability_mode == "regional" || try(local.subnet_id_by_source[v.subnet_source_id], "") != ""
  } : {}
  nat_enabled = length(local.nat_gateways_to_create) > 0
  # EIP é criado só para NAT ZONAL público. O regional em auto mode provisiona e
  # gerencia os próprios EIPs (e expande pelas AZs) sozinho.
  nat_zonal_keys = toset([for k, v in local.nat_gateways_to_create : k if v.availability_mode != "regional"])
}
resource "aws_eip" "nat" {
  for_each = local.nat_zonal_keys
  domain   = "vpc"
  tags     = merge(var.vpc_tags, { Name = "${var.vpc_name}-nat-eip-${each.key}" })
}
resource "aws_nat_gateway" "this" {
  for_each = local.nat_gateways_to_create
  # Regional (multi-AZ, auto mode): availability_mode=regional + vpc_id; SEM subnet
  # e SEM allocation_id (a AWS gerencia EIPs/AZs). connectivity_type DEVE ser public.
  # Zonal (1-por-subnet): subnet_id + allocation_id (EIP dedicado).
  availability_mode = each.value.availability_mode == "regional" ? "regional" : "zonal"
  vpc_id            = each.value.availability_mode == "regional" ? local.vpc_id : null
  connectivity_type = each.value.availability_mode == "regional" ? "public" : each.value.connectivity_type
  subnet_id         = each.value.availability_mode == "regional" ? null : lookup(local.subnet_id_by_source, each.value.subnet_source_id, null)
  allocation_id     = each.value.availability_mode == "regional" ? null : try(aws_eip.nat[each.key].id, null)
  tags = merge(var.vpc_tags, each.value.tags, { Name = try(each.value.tags["Name"], "${var.vpc_name}-nat") })
  depends_on = [aws_internet_gateway.this]
}
# --------------------------------------------------------------------
# EGRESS-ONLY INTERNET GATEWAY — recriado quando há rota IPv6 para ele.
# (Assim como IGW/NAT, o EOIGW morre junto com a VPC; a stack o recria.)
# --------------------------------------------------------------------
locals {
  needs_eoigw = (!local.vpc_found && length([
    for r in var.routes : r if r.target_kind == "egress_only_igw"
  ]) > 0)
}
resource "aws_egress_only_internet_gateway" "this" {
  count  = local.needs_eoigw ? 1 : 0
  vpc_id = local.vpc_id
  tags   = merge(var.vpc_tags, local.stack_marker_tags, { Name = "${var.vpc_name}-eoigw" })
}
# --------------------------------------------------------------------
# ROTAS (recurso unificado) — recria TODOS os tipos de alvo.
#
#  • igw / nat / egress_only_igw -> apontam para o recurso que a STACK
#    recria (esses gateways morrem com a VPC, então têm IDs novos).
#  • tgw -> find-or-create (transit_gateway.tf): resolvido por RAM/Name ou criado.
#  • peering / vgw -> FIND-OR-SKIP: consultados no DESTINO (data.external abaixo).
#    Achou o equivalente -> usa o ID; não achou -> a rota é PULADA (NÃO falha o
#    apply). Funciona cross-account: já não depende do ID literal da origem.
#  • eni -> SEMPRE pulada (skip): a rota aponta para a interface de um appliance/LB
#    que esta stack não gerencia; ENIs gerenciadas por ELB/Load Balancer Controller
#    são recriadas por ele (não precisam de rota estática). Avisado no CLUSTER-INFO.
#  • carrier -> FIND-OR-SKIP (Wavelength; morre com a VPC). Procurado no destino;
#    não achou -> rota pulada. Não falha o apply.
#  • core_network -> ID literal (Cloud WAN). Quando o core network é compartilhado
#    via RAM, o MESMO ARN vale no destino; se não estiver compartilhado, a rota falha.
# --------------------------------------------------------------------
# Find-or-skip de peering: procura no DESTINO uma conexão ATIVA que envolva a VPC e
# cujo outro lado cubra o CIDR da rota. Resultado vazio (não achou) -> rota pulada.
data "external" "peering_lookup" {
  for_each = (!local.vpc_found && var.recreate_external_routes) ? {
    for r in var.routes : r.key => r if r.target_kind == "peering"
  } : {}
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind          = "peering"
    exclude_value = var.cluster_name
    region        = var.region
    vpc_id        = local.vpc_id
    peer_cidr     = each.value.destination_cidr_block != "" ? each.value.destination_cidr_block : each.value.destination_ipv6_cidr_block
    profile       = var.aws_profile
  }
}
# Find-or-skip de VPN Gateway: procura o VGW anexado à VPC no DESTINO. Vazio -> pula.
data "external" "vgw_lookup" {
  for_each = (!local.vpc_found && var.recreate_external_routes) ? {
    for r in var.routes : r.key => r if r.target_kind == "vgw"
  } : {}
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind          = "vpn_gateway"
    exclude_value = var.cluster_name
    region        = var.region
    vpc_id        = local.vpc_id
    profile       = var.aws_profile
  }
}
# Find-or-skip de carrier gateway (Wavelength): procura o carrier da VPC no DESTINO.
data "external" "carrier_lookup" {
  for_each = (!local.vpc_found && var.recreate_external_routes) ? {
    for r in var.routes : r.key => r if r.target_kind == "carrier"
  } : {}
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind          = "carrier_gateway"
    exclude_value = var.cluster_name
    region        = var.region
    vpc_id        = local.vpc_id
    profile       = var.aws_profile
  }
}
locals {
  # Conjuntos de target_kind por argumento do aws_route.
  _route_kinds_gateway  = ["igw", "vgw"] # ambos usam gateway_id
  _route_kinds_external = ["tgw", "peering", "vgw", "eni", "carrier", "core_network"]
  # ID do alvo resolvido por rota: recurso recriado (igw/nat/eoigw) ou ID literal.
  # try() protege contra "Invalid index" quando o recurso tem count 0.
  route_target_id = {
    for r in var.routes : r.key => (
      r.target_kind == "igw" ? local.igw_id :
      r.target_kind == "nat" ? try(aws_nat_gateway.this[r.target_id].id, "") :
      r.target_kind == "egress_only_igw" ? try(aws_egress_only_internet_gateway.this[0].id, "") :
      # TGW: ID resolvido pelo find-or-create (RAM/por nome/recém-criado). Vazio
      # quando o lookup falhou e nada foi criado -> a rota é pulada.
      r.target_kind == "tgw" ? try(local.tgw_id_by_source[r.target_id], "") :
      # peering/vgw: FIND-OR-SKIP no destino (vazio = não achou -> rota pulada).
      r.target_kind == "peering" ? try(data.external.peering_lookup[r.key].result.id, "") :
      r.target_kind == "vgw" ? try(data.external.vgw_lookup[r.key].result.id, "") :
      # carrier: FIND-OR-SKIP (morre com a VPC; ID literal nunca vale em VPC nova).
      r.target_kind == "carrier" ? try(data.external.carrier_lookup[r.key].result.id, "") :
      # eni: SEMPRE pulada (interface de appliance/LB não gerenciado por esta stack).
      r.target_kind == "eni" ? "" :
      r.target_id
    )
  }
  # Rotas a efetivamente criar:
  #  - igw/nat/eoigw: sempre que a VPC é nova e o gateway correspondente foi criado.
  #  - externas: apenas quando recreate_external_routes = true e há ID literal.
  routes_to_create = {
    for r in var.routes : r.key => r
    if !local.vpc_found && (
      (r.target_kind == "igw" && local.igw_id != "") ||
      (r.target_kind == "nat" && local.route_target_id[r.key] != "") ||
      (r.target_kind == "egress_only_igw" && local.needs_eoigw) ||
      (contains(local._route_kinds_external, r.target_kind) && var.recreate_external_routes && local.route_target_id[r.key] != "")
    )
  }
}
resource "aws_route" "all" {
  for_each = local.routes_to_create
  route_table_id = aws_route_table.this[each.value.route_table_source_id].id
  # Destino: exatamente um (os demais ficam null).
  destination_cidr_block      = each.value.destination_cidr_block != "" ? each.value.destination_cidr_block : null
  destination_ipv6_cidr_block = each.value.destination_ipv6_cidr_block != "" ? each.value.destination_ipv6_cidr_block : null
  destination_prefix_list_id  = each.value.destination_prefix_list_id != "" ? each.value.destination_prefix_list_id : null
  # Alvo: exatamente um, conforme target_kind (os demais ficam null).
  gateway_id                = contains(local._route_kinds_gateway, each.value.target_kind) ? local.route_target_id[each.key] : null
  nat_gateway_id            = each.value.target_kind == "nat" ? local.route_target_id[each.key] : null
  egress_only_gateway_id    = each.value.target_kind == "egress_only_igw" ? local.route_target_id[each.key] : null
  transit_gateway_id        = each.value.target_kind == "tgw" ? local.route_target_id[each.key] : null
  vpc_peering_connection_id = each.value.target_kind == "peering" ? local.route_target_id[each.key] : null
  network_interface_id      = each.value.target_kind == "eni" ? local.route_target_id[each.key] : null
  carrier_gateway_id        = each.value.target_kind == "carrier" ? local.route_target_id[each.key] : null
  core_network_arn          = each.value.target_kind == "core_network" ? local.route_target_id[each.key] : null
  # Rotas "-> tgw-xxx" exigem que a VPC já esteja anexada ao TGW.
  depends_on = [aws_ec2_transit_gateway_vpc_attachment.this]
}
# --------------------------------------------------------------------
# TRANSIT GATEWAY ATTACHMENT — reanexa a VPC ao TGW (morre com a VPC).
# transit_gateway_id é literal da origem (válido na MESMA conta). Sem
# este attachment, as rotas para o TGW não funcionam.
# --------------------------------------------------------------------
resource "aws_ec2_transit_gateway_vpc_attachment" "this" {
  # O transit_gateway_id é RESOLVIDO pelo find-or-create (transit_gateway.tf):
  # RAM compartilhado -> mesmo ID; mesmo Name tag no destino -> ID existente;
  # senão -> ID do TGW recém-criado pela stack. Assim o attachment funciona
  # mesmo em OUTRA conta. Só é criado quando recreate_external_routes = true e a
  # VPC é nova; pula attachments cujas subnets não foram capturadas (subnet_ids
  # exige no mínimo 1) ou cujo TGW não pôde ser resolvido nem criado (id == "").
  for_each = (local.vpc_found || !var.recreate_external_routes) ? {} : {
    for k, v in var.transit_gateway_attachments : k => v
    if length(v.subnet_source_ids) > 0 && try(local.tgw_id_by_source[v.transit_gateway_id], "") != ""
  }
  transit_gateway_id = local.tgw_id_by_source[each.value.transit_gateway_id]
  vpc_id             = local.vpc_id
  subnet_ids         = compact([for s in each.value.subnet_source_ids : try(local.subnet_id_by_source[s], "")])
  dns_support            = each.value.dns_support ? "enable" : "disable"
  ipv6_support           = each.value.ipv6_support ? "enable" : "disable"
  appliance_mode_support = each.value.appliance_mode_support ? "enable" : "disable"
  tags = merge(each.value.tags, local.stack_marker_tags)
}
# --------------------------------------------------------------------
# VPC GATEWAY ENDPOINTS (S3/DynamoDB) — recriados e associados às route
# tables; o próprio endpoint recria as rotas por prefix-list.
# --------------------------------------------------------------------
resource "aws_vpc_endpoint" "gateway" {
  for_each = local.vpc_found ? {} : var.gateway_endpoints
  vpc_id            = local.vpc_id
  service_name      = each.value.service_name
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for r in each.value.route_table_source_ids : aws_route_table.this[r].id]
  # __DEST_ACCOUNT__ (conta de origem reescrita pelo importer) -> conta de destino.
  policy = each.value.policy != "" ? replace(
    each.value.policy, "__DEST_ACCOUNT__", data.aws_caller_identity.current.account_id
  ) : null
  tags = merge(each.value.tags, local.stack_marker_tags)
}
resource "aws_vpc_endpoint" "interface" {
  # Interface endpoints (ECR, STS, CloudWatch Logs, EC2, etc.) — só quando a VPC
  # é nova. Pula os que ficaram sem subnets capturadas (exigem no mínimo 1).
  for_each = local.vpc_found ? {} : {
    for k, v in var.interface_endpoints : k => v if length(v.subnet_source_ids) > 0
  }
  vpc_id              = local.vpc_id
  service_name        = each.value.service_name
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = each.value.private_dns_enabled
  # ip_address_type fiel à origem (ipv4/dualstack/ipv6); omite quando não veio.
  ip_address_type = each.value.ip_address_type != "" ? each.value.ip_address_type : null
  # dns_options só quando há algo a setar. private_dns_only_for_inbound_resolver_endpoint
  # é emitido APENAS quando true (com private_dns_enabled): emiti-lo como false junto
  # com private DNS quebra alguns serviços (bug do provider, issues #33689/#982).
  dynamic "dns_options" {
    for_each = (each.value.dns_record_ip_type != "" ||
                each.value.private_dns_only_for_inbound_resolver_endpoint) ? [1] : []
    content {
      dns_record_ip_type = each.value.dns_record_ip_type != "" ? each.value.dns_record_ip_type : null
      private_dns_only_for_inbound_resolver_endpoint = (
        each.value.private_dns_enabled && each.value.private_dns_only_for_inbound_resolver_endpoint
      ) ? true : null
    }
  }
  # Subnets remapeadas origem -> destino (ignora as não capturadas).
  subnet_ids = [
    for s in each.value.subnet_source_ids : local.subnet_id_by_source[s]
    if try(local.subnet_id_by_source[s], "") != ""
  ]
  # SGs remapeados para o destino:
  #  • o Cluster SG da origem -> Cluster SG do cluster NOVO (mesmas regras manuais,
  #    recriadas via cluster_sg_ingress/egress_rules). Isso preserva o controle de
  #    acesso AO endpoint. (Cria dependência endpoint->cluster, aceitável: o cluster
  #    não precisa do endpoint, e os nós que precisam sobem depois do cluster.)
  #  • demais SGs -> find-or-create (sg_id_by_source); fallback literal se não capturado.
  # Lista vazia -> null (AWS associa o SG default da VPC).
  security_group_ids = length(each.value.security_group_source_ids) > 0 ? [
    for s in each.value.security_group_source_ids :
    s == var.source_cluster_security_group_id
      ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
      : (try(local.sg_id_by_source[s], "") != "" ? local.sg_id_by_source[s] : s)
  ] : null
  # __DEST_ACCOUNT__ (conta de origem reescrita pelo importer) -> conta de destino.
  policy = each.value.policy != "" ? replace(
    each.value.policy, "__DEST_ACCOUNT__", data.aws_caller_identity.current.account_id
  ) : null
  tags = merge(each.value.tags, local.stack_marker_tags)
}
"""
HCL_TRANSIT_GATEWAY_TF = """
# =====================================================================
# TRANSIT GATEWAY — estratégia FIND-OR-CREATE (replicação cross-account)
#
# Faz a rota "-> tgw-xxx" e o attachment funcionarem em QUALQUER conta. Para
# cada TGW referenciado, o lookup (scripts/aws_lookup.py, kind=transit_gateway)
# tenta em cascata, em tempo de plan:
#   1) MESMO ID visível no destino (TGW compartilhado via AWS RAM) -> usa direto;
#   2) MESMO Name tag, owned pela conta de destino -> usa o ID existente;
#   3) Não encontrado -> o Terraform CRIA um TGW novo com a MESMA configuração da
#      origem (ASN, dns_support, vpn_ecmp_support, etc.) + as route tables
#      customizadas e suas rotas estáticas blackhole.
# O ID efetivo (encontrado ou criado) vai para local.tgw_id_by_source, usado pelo
# attachment e pelas rotas em network.tf.
#
# Só age quando recreate_external_routes = true e a VPC é nova (quando a VPC já
# existe no destino, assume-se que a malha — inclusive o TGW/attachment — já
# existe e nada é recriado).
# =====================================================================
locals {
  # Habilita o find-or-create de TGW: recriar alvos externos E VPC nova.
  _tgw_enabled = var.recreate_external_routes && !local.vpc_found
}
# Lookup do TGW na conta de DESTINO (3 estratégias em cascata).
data "external" "tgw_lookup" {
  for_each = local._tgw_enabled ? var.transit_gateways : {}
  program  = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind          = "transit_gateway"
    exclude_value = var.cluster_name
    region        = var.region
    source_tgw_id = each.key
    tgw_name      = each.value.name
    profile       = var.aws_profile
  }
}
locals {
  # TGWs encontrados no destino (via RAM ou Name tag) -> NÃO são recriados.
  tgw_found = {
    for tgw_id, cfg in var.transit_gateways :
    tgw_id => (try(data.external.tgw_lookup[tgw_id].result.found, "false") == "true")
  }
}
# Cria o TGW novo apenas quando habilitado E não foi encontrado no destino.
resource "aws_ec2_transit_gateway" "this" {
  for_each = {
    for tgw_id, cfg in var.transit_gateways : tgw_id => cfg
    if local._tgw_enabled && !local.tgw_found[tgw_id]
  }
  description                     = each.value.description != "" ? each.value.description : null
  amazon_side_asn                 = each.value.amazon_side_asn
  auto_accept_shared_attachments  = each.value.auto_accept_shared_attachments
  default_route_table_association = each.value.default_route_table_association
  default_route_table_propagation = each.value.default_route_table_propagation
  dns_support                     = each.value.dns_support
  vpn_ecmp_support                = each.value.vpn_ecmp_support
  multicast_support               = each.value.multicast_support
  # Tag-marca no PRÓPRIO TGW (o lookup a ignora -> find-or-create idempotente).
  # eks-importer:source-id guarda o tgw-id de origem para rastreabilidade.
  tags = merge(each.value.tags, local.stack_marker_tags, {
    Name                     = each.value.name
    "eks-importer:source-id" = each.key
  })
}
locals {
  # ID efetivo do TGW por ID de ORIGEM (tabela de tradução usada por
  # network.tf): encontrado (RAM/Name) -> ID do destino; senão -> ID do TGW
  # recém-criado; senão (lookup desligado / não criado) -> "".
  tgw_id_by_source = {
    for tgw_id, cfg in var.transit_gateways : tgw_id => (
      local.tgw_found[tgw_id]
      ? data.external.tgw_lookup[tgw_id].result.id
      : try(aws_ec2_transit_gateway.this[tgw_id].id, "")
    )
  }
  # Route tables CUSTOMIZADAS a recriar — só nos TGWs que ESTA stack criou
  # (os encontrados via RAM/Name já têm as suas, e não as gerenciamos).
  _tgw_route_tables = {
    for item in flatten([
      for tgw_id, cfg in var.transit_gateways : [
        for rt_id, rt in cfg.route_tables : {
          key    = "${tgw_id}__${rt_id}"
          tgw_id = tgw_id
          tags   = rt.tags
        }
      ]
    ]) : item.key => item
    if try(aws_ec2_transit_gateway.this[item.tgw_id].id, "") != ""
  }
  # Rotas estáticas BLACKHOLE das route tables customizadas. Rotas estáticas que
  # apontam para um attachment NÃO são recriadas (o attachment-alvo não é
  # resolvido aqui; veja a nota no CLUSTER-INFO) — só as blackhole, que não
  # dependem de attachment.
  _tgw_static_routes = {
    for item in flatten([
      for tgw_id, cfg in var.transit_gateways : [
        for rt_id, rt in cfg.route_tables : [
          for route in rt.static_routes : {
            key    = "${tgw_id}__${rt_id}__${route.cidr}"
            tgw_id = tgw_id
            rt_id  = rt_id
            cidr   = route.cidr
          } if route.blackhole
        ]
      ]
    ]) : item.key => item
    if try(aws_ec2_transit_gateway.this[item.tgw_id].id, "") != ""
  }
}
resource "aws_ec2_transit_gateway_route_table" "this" {
  for_each           = local._tgw_route_tables
  transit_gateway_id = aws_ec2_transit_gateway.this[each.value.tgw_id].id
  tags               = merge(each.value.tags, local.stack_marker_tags)
}
resource "aws_ec2_transit_gateway_route" "this" {
  for_each = local._tgw_static_routes
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.this[
    "${each.value.tgw_id}__${each.value.rt_id}"
  ].id
  destination_cidr_block = each.value.cidr
  blackhole              = true
}
"""
HCL_IAM_TF = """
# =====================================================================
# IAM ROLES — estratégia FIND-OR-CREATE
#
# IAM é global na conta. A chave natural é o NOME da role (o ARN muda
# entre contas porque embute o account id). Para cada role referenciada
# pelo cluster/nodegroups/fargate/auto-mode:
#   • Já existe (mesmo nome)? -> reutiliza o ARN existente.
#   • Não existe? -> cria com trust policy, managed policies e inline
#     policies idênticas à origem.
# =====================================================================
data "external" "iam_role_lookup" {
  for_each = var.iam_roles
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "iam_role"
    exclude_value = var.cluster_name
    name    = each.key
    profile = var.aws_profile
  }
}
locals {
  iam_role_found = {
    for name, _ in var.iam_roles : name => (
      var.disable_resource_reuse ? false : (data.external.iam_role_lookup[name].result.arn != "")
    )
  }
}
resource "aws_iam_role" "this" {
  for_each = { for name, cfg in var.iam_roles : name => cfg if !local.iam_role_found[name] }
  name                 = each.key
  path                 = each.value.path
  description          = each.value.description
  # A trust policy pode conter o token __DEST_ACCOUNT__ no lugar da conta de
  # ORIGEM (reescrito pelo importer); aqui ele vira a conta de DESTINO real.
  assume_role_policy = replace(
    each.value.assume_role_policy,
    "__DEST_ACCOUNT__",
    data.aws_caller_identity.current.account_id
  )
  max_session_duration = each.value.max_session_duration
  permissions_boundary = each.value.permissions_boundary != "" ? each.value.permissions_boundary : null
  tags = merge(each.value.tags, local.stack_marker_tags)
}
locals {
  # ARN efetivo por NOME — ESTÁVEL (conhecido em plan).
  #
  # IMPORTANTE: NÃO derivamos o ARN de `iam_role_found ? data... : aws_iam_role.this[...].arn`.
  # Aquilo muda de valor conforme a role é encontrada ou criada, e quando vira
  # "known after apply" FORÇA a substituição do cluster (compute_config.node_role_arn).
  # Como IAM é global e o nome da role é fixo, o ARN no destino é determinístico:
  # é o source_arn com o account de ORIGEM trocado pelo de DESTINO. Mesma conta =
  # ARN idêntico ao de origem. Isso mantém node_role_arn/role_arn estáveis e evita
  # que o status found/created do find-or-create cause replacement do cluster.
  iam_role_arn_by_name = {
    for name, cfg in var.iam_roles : name => replace(
      cfg.source_arn, var.source_account_id, data.aws_caller_identity.current.account_id
    )
  }
  # ARN efetivo por ARN DE ORIGEM — "tabela de tradução" usada por
  # cluster/nodegroups/fargate (que guardam o ARN original da origem).
  iam_role_arn_by_source_arn = {
    for name, cfg in var.iam_roles : cfg.source_arn => local.iam_role_arn_by_name[name]
  }
  # Nome da role por ARN de origem (instance profiles referenciam a role por nome).
  iam_role_name_by_source_arn = {
    for name, cfg in var.iam_roles : cfg.source_arn => name
  }
  # Prefixos de ARN IAM da conta de ORIGEM e de DESTINO.
  _src_iam_prefix = "arn:aws:iam::${var.source_account_id}:"
  _dst_iam_prefix = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:"
  # Todos os ARNs de role/principal que aparecem em pod identity, add-ons e
  # access entries (precisam ser traduzidos da origem para o destino).
  _all_principal_arns = distinct(concat(
    [for a in values(var.pod_identity_associations) : a.role_arn],
    flatten([for ad in values(var.addons) : [for p in ad.pod_identity_associations : p.role_arn]]),
    [for ad in values(var.addons) : ad.service_account_role_arn if ad.service_account_role_arn != null],
    [for e in values(var.access_entries) : e.principal_arn],
  ))
  # Tradução final por ARN de origem:
  #   - se a role foi capturada/recriada (find-or-create), usa o ARN real dela;
  #   - se for um USER recriado (find-or-create), aponta para o ARN dele (isso
  #     cria a dependência: o access entry só é criado depois do user existir);
  #   - senão (federação/role não capturada), reescreve só o account-id da origem.
  translated_principal_arn = {
    for arn in local._all_principal_arns : arn => (
      contains(keys(local.iam_role_arn_by_source_arn), arn)
      ? local.iam_role_arn_by_source_arn[arn]
      : (
        length(regexall(":user/", arn)) > 0 && contains(keys(local.iam_user_arn_by_name), element(split("/", arn), length(split("/", arn)) - 1))
        ? local.iam_user_arn_by_name[element(split("/", arn), length(split("/", arn)) - 1)]
        : replace(arn, local._src_iam_prefix, local._dst_iam_prefix)
      )
    )
  }
}
# Conta de DESTINO (resolvida no apply) — usada para reescrever ARNs de
# principals que não são recriados (federação).
data "aws_caller_identity" "current" {}
# --------------------------------------------------------------------
# Users IAM — estratégia FIND-OR-CREATE (por nome)
#
# Users referenciados por access entries são recriados VAZIOS (sem credenciais)
# para que o principal exista no destino e o access entry funcione. Find-or-create:
#   • Já existe no destino (mesmo nome)? -> reutiliza.
#   • Não existe? -> cria (sem chaves/senha; adicione credenciais/SSO depois).
# --------------------------------------------------------------------
data "external" "user_lookup" {
  for_each = var.iam_users
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "iam_user"
    exclude_value = var.cluster_name
    name    = each.key
    profile = var.aws_profile
  }
}
locals {
  iam_user_found = {
    for name, _ in var.iam_users :
    name => (var.disable_resource_reuse ? false : (data.external.user_lookup[name].result.arn != ""))
  }
}
resource "aws_iam_user" "this" {
  for_each = { for name, cfg in var.iam_users : name => cfg if !local.iam_user_found[name] }
  name = each.key
  path = each.value.path
  tags = local.stack_marker_tags
}
locals {
  iam_user_arn_by_name = {
    for name, _ in var.iam_users : name => try(
      aws_iam_user.this[name].arn,
      data.external.user_lookup[name].result.arn,
      ""
    )
  }
}
# --------------------------------------------------------------------
# Policies CUSTOMER-MANAGED — estratégia FIND-OR-CREATE (por nome)
#
# As policies customer-managed da origem (arn:aws:iam::<conta-origem>:policy/...)
# não existem em outra conta. Para cada uma referenciada por alguma role:
#   • Já existe no destino (mesmo nome)? -> reutiliza.
#   • Não existe? -> cria com o mesmo documento (account-id reescrito p/ destino).
# As policies da AWS (arn:aws:iam::aws:policy/...) são globais e NÃO entram aqui.
# --------------------------------------------------------------------
data "external" "policy_lookup" {
  for_each = var.customer_managed_policies
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "iam_policy"
    exclude_value = var.cluster_name
    name    = each.key
    profile = var.aws_profile
  }
}
locals {
  customer_policy_found = {
    for name, _ in var.customer_managed_policies :
    name => (var.disable_resource_reuse ? false : (data.external.policy_lookup[name].result.arn != ""))
  }
}
resource "aws_iam_policy" "this" {
  for_each = { for name, cfg in var.customer_managed_policies : name => cfg if !local.customer_policy_found[name] }
  name        = each.key
  path        = each.value.path
  description = each.value.description
  # __DEST_ACCOUNT__ (conta de origem reescrita pelo importer) -> conta de destino.
  policy = replace(
    each.value.document,
    "__DEST_ACCOUNT__",
    data.aws_caller_identity.current.account_id
  )
  tags = local.stack_marker_tags
}
locals {
  # ARN final de cada policy customer-managed: a existente (found) ou a recriada.
  customer_policy_arn_by_name = {
    for name, _ in var.customer_managed_policies : name => try(
      aws_iam_policy.this[name].arn,
      data.external.policy_lookup[name].result.arn,
      ""
    )
  }
}
# --------------------------------------------------------------------
# Managed policies (anexadas apenas quando criamos a role)
#   • AWS-managed (arn:aws:iam::aws:policy/...) -> anexa o ARN direto.
#   • Customer-managed -> anexa o ARN da policy recriada/encontrada no destino.
# --------------------------------------------------------------------
locals {
  _managed_attachments = flatten([
    for name, cfg in var.iam_roles : [
      for arn in cfg.managed_policy_arns : {
        key        = "${name}::${arn}"
        role       = name
        pol_name   = element(split("/", arn), length(split("/", arn)) - 1)
        source_arn = arn
      }
    ] if !local.iam_role_found[name]
  ])
  managed_attachments = {
    for item in local._managed_attachments : item.key => merge(item, {
      policy_arn = contains(keys(var.customer_managed_policies), item.pol_name) ? local.customer_policy_arn_by_name[item.pol_name] : item.source_arn
    })
  }
}
resource "aws_iam_role_policy_attachment" "this" {
  for_each = local.managed_attachments
  role       = aws_iam_role.this[each.value.role].name
  policy_arn = each.value.policy_arn
}
# --------------------------------------------------------------------
# Inline policies (criadas apenas quando criamos a role)
# --------------------------------------------------------------------
locals {
  _inline_policies = flatten([
    for name, cfg in var.iam_roles : [
      for pol_name, pol_doc in cfg.inline_policies : {
        key         = "${name}::${pol_name}"
        role        = name
        policy_name = pol_name
        policy      = pol_doc
      }
    ] if !local.iam_role_found[name]
  ])
  inline_policies = { for item in local._inline_policies : item.key => item }
}
resource "aws_iam_role_policy" "this" {
  for_each = local.inline_policies
  name   = each.value.policy_name
  role   = aws_iam_role.this[each.value.role].name
  policy = each.value.policy
}
"""
HCL_SECURITY_GROUPS_TF = """
# =====================================================================
# SECURITY GROUPS (adicionais) — estratégia FIND-OR-CREATE
#
# Gerencia os security groups ADICIONAIS do cluster (os de
# var.security_group_ids, ex.: workers SG e control plane SG). O
# "Cluster Security Group" em si é criado e gerenciado pelo EKS e NÃO é
# criado aqui, mas as REGRAS manuais adicionadas a ele SÃO recriadas
# (veja a seção "REGRAS DO CLUSTER SECURITY GROUP" mais abaixo).
#
# Cada SG é procurado por (vpc-id + group-name):
#   • Já existe? -> reutiliza o ID.
#   • Não existe? -> cria com as MESMAS regras (ingress/egress).
#
# Regras são recursos individuais (aws_vpc_security_group_*_rule), um
# alvo por regra. Referências a OUTRO SG são religadas ao ID novo:
#   • para SGs capturados -> via a tabela sg_id_by_source (inclui auto-
#     referência);
#   • para o Cluster SG do EKS -> via o token "__CLUSTER_SG__", que aponta
#     para o Cluster SG do cluster de destino.
# Referências a SGs criados em runtime (Load Balancer Controller) foram
# descartadas pelo importer (não existem no apply; veja CLUSTER-INFO.md).
# =====================================================================
data "external" "sg_lookup" {
  for_each = local.vpc_found ? var.security_groups : {}
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "security_group"
    exclude_value = var.cluster_name
    region  = var.region
    vpc_id  = local.vpc_id
    name    = each.value.name
    profile = var.aws_profile
  }
}
locals {
  # O default VPC security group (group-name "default") é RESERVADO pela AWS:
  # não pode ser criado com aws_security_group (erro InvalidGroup.Reserved). É
  # adotado via aws_default_security_group quando a VPC é nova, ou localizado via
  # lookup quando a VPC é reusada.
  default_sg_keys = [for k, v in var.security_groups : k if v.name == "default"]
  has_default_sg  = length(local.default_sg_keys) > 0
  default_sg_key  = local.has_default_sg ? local.default_sg_keys[0] : "__NO_DEFAULT_SG__"
  sg_found = {
    for k, v in var.security_groups : k => (
      local.vpc_found ? try(data.external.sg_lookup[k].result.id, "") != "" : false
    )
  }
}
resource "aws_security_group" "this" {
  # Exclui o default SG (name "default" é reservado — vai para aws_default_security_group).
  for_each = { for k, v in var.security_groups : k => v if !local.sg_found[k] && v.name != "default" }
  name        = each.value.name
  description = each.value.description
  vpc_id      = local.vpc_id
  tags = merge(each.value.tags, local.stack_marker_tags)
  # Evita conflito de auto-referência durante o create/update.
  lifecycle {
    create_before_destroy = true
  }
}
# O default VPC security group existe automaticamente em toda VPC e NÃO pode ser
# criado (group-name "default" é reservado). Aqui ele é ADOTADO (não criado) e
# recebe as MESMAS regras da origem. Só quando a VPC é nova; quando a VPC é
# reusada, o default SG existente é localizado via lookup e não é tocado.
resource "aws_default_security_group" "this" {
  count  = (local.has_default_sg && !local.vpc_found) ? 1 : 0
  vpc_id = local.vpc_id
  tags   = merge(try(var.security_groups[local.default_sg_key].tags, {}), local.stack_marker_tags)
  dynamic "ingress" {
    for_each = [
      for r in var.sg_ingress_rules : r
      if r.sg_source_id == local.default_sg_key && r.referenced_sg_source_id != "__CLUSTER_SG__"
    ]
    content {
      protocol         = ingress.value.ip_protocol
      from_port        = ingress.value.from_port == null ? 0 : ingress.value.from_port
      to_port          = ingress.value.to_port == null ? 0 : ingress.value.to_port
      cidr_blocks      = ingress.value.cidr_ipv4 != "" ? [ingress.value.cidr_ipv4] : null
      ipv6_cidr_blocks = ingress.value.cidr_ipv6 != "" ? [ingress.value.cidr_ipv6] : null
      prefix_list_ids  = ingress.value.prefix_list_id != "" ? [ingress.value.prefix_list_id] : null
      self             = ingress.value.referenced_sg_source_id == local.default_sg_key ? true : null
      security_groups = (
        ingress.value.referenced_sg_source_id != "" && ingress.value.referenced_sg_source_id != local.default_sg_key
      ) ? [local.sg_id_by_source[ingress.value.referenced_sg_source_id]] : null
      description = ingress.value.description
    }
  }
  dynamic "egress" {
    for_each = [
      for r in var.sg_egress_rules : r
      if r.sg_source_id == local.default_sg_key && r.referenced_sg_source_id != "__CLUSTER_SG__"
    ]
    content {
      protocol         = egress.value.ip_protocol
      from_port        = egress.value.from_port == null ? 0 : egress.value.from_port
      to_port          = egress.value.to_port == null ? 0 : egress.value.to_port
      cidr_blocks      = egress.value.cidr_ipv4 != "" ? [egress.value.cidr_ipv4] : null
      ipv6_cidr_blocks = egress.value.cidr_ipv6 != "" ? [egress.value.cidr_ipv6] : null
      prefix_list_ids  = egress.value.prefix_list_id != "" ? [egress.value.prefix_list_id] : null
      self             = egress.value.referenced_sg_source_id == local.default_sg_key ? true : null
      security_groups = (
        egress.value.referenced_sg_source_id != "" && egress.value.referenced_sg_source_id != local.default_sg_key
      ) ? [local.sg_id_by_source[egress.value.referenced_sg_source_id]] : null
      description = egress.value.description
    }
  }
}
locals {
  # ID de SG na origem -> ID no destino (tabela de tradução).
  sg_id_by_source = {
    for src_id, cfg in var.security_groups : src_id => (
      cfg.name == "default"
      ? (local.vpc_found
        ? try(data.external.sg_lookup[src_id].result.id, "")
        : try(aws_default_security_group.this[0].id, ""))
      : try(
        aws_security_group.this[src_id].id,
        data.external.sg_lookup[src_id].result.id,
        ""
      )
    )
  }
}
resource "aws_vpc_security_group_ingress_rule" "this" {
  for_each = {
    for r in var.sg_ingress_rules : r.key => r
    if !local.sg_found[r.sg_source_id] && r.sg_source_id != local.default_sg_key
  }
  security_group_id = local.sg_id_by_source[each.value.sg_source_id]
  ip_protocol       = each.value.ip_protocol
  from_port         = each.value.from_port
  to_port           = each.value.to_port
  cidr_ipv4         = each.value.cidr_ipv4 != "" ? each.value.cidr_ipv4 : null
  cidr_ipv6         = each.value.cidr_ipv6 != "" ? each.value.cidr_ipv6 : null
  prefix_list_id    = each.value.prefix_list_id != "" ? each.value.prefix_list_id : null
  referenced_security_group_id = (
    each.value.referenced_sg_source_id == "__CLUSTER_SG__"
      ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
    : each.value.referenced_sg_source_id != ""
      ? local.sg_id_by_source[each.value.referenced_sg_source_id]
    : null
  )
  description = each.value.description
}
resource "aws_vpc_security_group_egress_rule" "this" {
  for_each = {
    for r in var.sg_egress_rules : r.key => r
    if !local.sg_found[r.sg_source_id] && r.sg_source_id != local.default_sg_key
  }
  security_group_id = local.sg_id_by_source[each.value.sg_source_id]
  ip_protocol       = each.value.ip_protocol
  from_port         = each.value.from_port
  to_port           = each.value.to_port
  cidr_ipv4         = each.value.cidr_ipv4 != "" ? each.value.cidr_ipv4 : null
  cidr_ipv6         = each.value.cidr_ipv6 != "" ? each.value.cidr_ipv6 : null
  prefix_list_id    = each.value.prefix_list_id != "" ? each.value.prefix_list_id : null
  referenced_security_group_id = (
    each.value.referenced_sg_source_id == "__CLUSTER_SG__"
      ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
    : each.value.referenced_sg_source_id != ""
      ? local.sg_id_by_source[each.value.referenced_sg_source_id]
    : null
  )
  description = each.value.description
}
# ---------------------------------------------------------------------
# REGRAS DO CLUSTER SECURITY GROUP (gerenciado pelo EKS)
#
# O Cluster SG é criado pelo próprio EKS; aqui NÃO o criamos, apenas
# anexamos a ele as regras que foram ADICIONADAS manualmente na origem
# (ex.: liberar uma VPC de peering, liberar o workers SG, abrir uma porta).
# O ID do Cluster SG do destino só existe após o cluster ser criado, por
# isso vem de aws_eks_cluster.main.vpc_config[0].cluster_security_group_id.
#
# As regras DEFAULT do EKS (self all-traffic / egress all-traffic) NÃO entram
# aqui (o importer já as removeu) para não dar erro de duplicata, pois o EKS
# as recria sozinho. Referência ao próprio Cluster SG (__CLUSTER_SG__) e a
# SGs capturados (sg_id_by_source) são religadas ao destino.
# ---------------------------------------------------------------------
resource "aws_vpc_security_group_ingress_rule" "cluster_sg" {
  for_each = { for r in var.cluster_sg_ingress_rules : r.key => r }
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol       = each.value.ip_protocol
  from_port         = each.value.from_port
  to_port           = each.value.to_port
  cidr_ipv4         = each.value.cidr_ipv4 != "" ? each.value.cidr_ipv4 : null
  cidr_ipv6         = each.value.cidr_ipv6 != "" ? each.value.cidr_ipv6 : null
  prefix_list_id    = each.value.prefix_list_id != "" ? each.value.prefix_list_id : null
  referenced_security_group_id = (
    each.value.referenced_sg_source_id == "__CLUSTER_SG__"
      ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
    : each.value.referenced_sg_source_id != ""
      ? local.sg_id_by_source[each.value.referenced_sg_source_id]
    : null
  )
  description = each.value.description
}
resource "aws_vpc_security_group_egress_rule" "cluster_sg" {
  for_each = { for r in var.cluster_sg_egress_rules : r.key => r }
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol       = each.value.ip_protocol
  from_port         = each.value.from_port
  to_port           = each.value.to_port
  cidr_ipv4         = each.value.cidr_ipv4 != "" ? each.value.cidr_ipv4 : null
  cidr_ipv6         = each.value.cidr_ipv6 != "" ? each.value.cidr_ipv6 : null
  prefix_list_id    = each.value.prefix_list_id != "" ? each.value.prefix_list_id : null
  referenced_security_group_id = (
    each.value.referenced_sg_source_id == "__CLUSTER_SG__"
      ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
    : each.value.referenced_sg_source_id != ""
      ? local.sg_id_by_source[each.value.referenced_sg_source_id]
    : null
  )
  description = each.value.description
}
"""
HCL_LOCALS_TF = """
# =====================================================================
# WIRING — traduz tudo que veio da conta de ORIGEM para os IDs/ARNs
# efetivos na conta de DESTINO (encontrados ou recém-criados).
#
# As tabelas de tradução vêm de:
#   • subnet_id_by_source        (network.tf)
#   • sg_id_by_source            (security_groups.tf)
#   • iam_role_arn_by_source_arn (iam.tf)
# =====================================================================
locals {
  # Tag-marca colocada em TODO recurso de base que ESTA stack cria (find-or-create).
  # Os lookups (aws_lookup.py) ignoram recursos com esta marca == este cluster, o que
  # torna o find-or-create idempotente automaticamente: o que a stack criou continua
  # gerenciado (nunca é "reencontrado" e destruído) e só o que pré-existe é reusado.
  # Não precisa mais setar disable_resource_reuse na mão.
  stack_marker_tags = { "eks-importer:stack" = var.cluster_name }
  # Subnets do CONTROL PLANE (cluster) — IDs de origem -> destino.
  cluster_subnet_ids = [for s in var.subnet_ids : local.subnet_id_by_source[s]]
  # Security groups adicionais do cluster — IDs de origem -> destino.
  cluster_security_group_ids = [for s in var.security_group_ids : local.sg_id_by_source[s]]
  # Role do cluster — ARN de origem -> destino.
  cluster_role_arn = local.iam_role_arn_by_source_arn[var.cluster_role_arn]
  # Role das instâncias do Auto Mode — ARN de origem -> destino (se houver).
  auto_mode_node_role_arn = (
    var.auto_mode_enabled && var.auto_mode_node_role_arn != null
    ? local.iam_role_arn_by_source_arn[var.auto_mode_node_role_arn]
    : null
  )
}
"""
HCL_LAUNCH_TEMPLATES_TF = """
# =====================================================================
# LAUNCH TEMPLATES — find-or-create (por nome), recriados para o cluster NOVO.
#
# IMPORTANTE: o user-data da origem é OMITIDO de propósito. Em nodegroup
# gerenciado, quando o LT não tem user-data, o EKS injeta automaticamente o
# bootstrap do cluster de DESTINO (endpoint/CA corretos). O user-data da origem
# apontaria para o cluster antigo. O conteúdo original é salvo em
# 'launch-templates-userdata/' para referência.
#
# Security groups são remapeados (origem -> destino); o Cluster SG do EKS é
# remapeado para o SG do cluster novo. O instance profile é recriado.
# =====================================================================
# ---- Instance profiles (recriados; a role já é capturada em iam.tf) ----
data "external" "instance_profile_lookup" {
  for_each = var.instance_profiles
  program  = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "instance_profile"
    exclude_value = var.cluster_name
    name    = each.key
    profile = var.aws_profile
  }
}
locals {
  instance_profile_found = {
    for name, cfg in var.instance_profiles :
    name => (var.disable_resource_reuse ? false : (data.external.instance_profile_lookup[name].result.name != ""))
  }
}
resource "aws_iam_instance_profile" "this" {
  for_each = { for name, cfg in var.instance_profiles : name => cfg if !local.instance_profile_found[name] }
  name     = each.key
  role     = local.iam_role_name_by_source_arn[each.value.source_role_arn]
  tags       = local.stack_marker_tags
  depends_on = [aws_iam_role.this]
}
# ---- Remapeamento de SGs usados nos launch templates ----
locals {
  _lt_all_sg_sources = distinct(flatten([
    for lt in values(var.launch_templates) : lt.vpc_security_group_source_ids
  ]))
  # Cada SG de origem -> SG no destino:
  #   - se é um SG gerenciado/capturado, usa a tabela de tradução;
  #   - se é o Cluster SG do EKS (origem), usa o Cluster SG do cluster novo;
  #   - senão, vazio (descartado).
  lt_sg_translate = {
    for src in local._lt_all_sg_sources : src => (
      contains(keys(local.sg_id_by_source), src) ? local.sg_id_by_source[src] : (
        src == var.source_cluster_security_group_id
        ? aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
        : ""
      )
    )
  }
}
# ---- Key pairs EC2 (find-or-create por nome) ----
# Recria no destino o key pair da origem com a MESMA chave pública. A chave
# privada que você já baixou continua válida (é par da mesma pública).
data "external" "key_pair_lookup" {
  for_each = var.key_pairs
  program = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "key_pair"
    exclude_value = var.cluster_name
    name    = each.key
    region  = var.region
    profile = var.aws_profile
  }
}
locals {
  key_pair_found = {
    for name, _ in var.key_pairs :
    name => (var.disable_resource_reuse ? false : (data.external.key_pair_lookup[name].result.name != ""))
  }
}
resource "aws_key_pair" "this" {
  for_each = { for name, cfg in var.key_pairs : name => cfg if !local.key_pair_found[name] }
  key_name   = each.key
  public_key = each.value.public_key
  tags       = merge(each.value.tags, local.stack_marker_tags)
}
locals {
  # Nome do key pair (existente ou recriado). Usar este local no LT cria a
  # dependência: o LT só é criado depois do key pair existir.
  key_pair_name_by_name = {
    for name, _ in var.key_pairs : name => try(
      aws_key_pair.this[name].key_name,
      data.external.key_pair_lookup[name].result.name,
      ""
    )
  }
}
# ---- Launch templates ----
data "external" "lt_lookup" {
  for_each = var.launch_templates
  program  = ["python3", "${path.module}/scripts/aws_lookup.py"]
  query = {
    kind    = "launch_template"
    exclude_value = var.cluster_name
    name    = each.value.name
    region  = var.region
    profile = var.aws_profile
  }
}
locals {
  lt_found = {
    for k, cfg in var.launch_templates : k => (
      var.disable_resource_reuse ? false : (data.external.lt_lookup[k].result.id != "")
    )
  }
}
resource "aws_launch_template" "this" {
  for_each = { for k, cfg in var.launch_templates : k => cfg if !local.lt_found[k] }
  name     = each.value.name
  # Tag-marca no PRÓPRIO launch template (é isso que o lookup checa).
  tags = local.stack_marker_tags
  image_id      = each.value.image_id != "" ? each.value.image_id : null
  instance_type = each.value.instance_type != "" ? each.value.instance_type : null
  key_name      = each.value.key_name != "" ? local.key_pair_name_by_name[each.value.key_name] : null
  ebs_optimized = each.value.ebs_optimized != "" ? each.value.ebs_optimized : null
  # SGs remapeados; descarta os que não puderam ser resolvidos.
  vpc_security_group_ids = [
    for s in each.value.vpc_security_group_source_ids :
    local.lt_sg_translate[s] if local.lt_sg_translate[s] != ""
  ]
  dynamic "iam_instance_profile" {
    for_each = each.value.iam_instance_profile_name != "" ? [each.value.iam_instance_profile_name] : []
    content {
      name = iam_instance_profile.value
    }
  }
  dynamic "monitoring" {
    for_each = each.value.monitoring_enabled ? [1] : []
    content {
      enabled = true
    }
  }
  dynamic "block_device_mappings" {
    for_each = each.value.block_device_mappings
    content {
      device_name = block_device_mappings.value.device_name
      ebs {
        volume_size           = block_device_mappings.value.volume_size
        volume_type           = block_device_mappings.value.volume_type != "" ? block_device_mappings.value.volume_type : null
        iops                  = block_device_mappings.value.iops
        throughput            = block_device_mappings.value.throughput
        encrypted             = block_device_mappings.value.encrypted != "" ? block_device_mappings.value.encrypted : null
        delete_on_termination = block_device_mappings.value.delete_on_termination != "" ? block_device_mappings.value.delete_on_termination : null
      }
    }
  }
  dynamic "metadata_options" {
    for_each = each.value.metadata_options.http_endpoint != "" ? [each.value.metadata_options] : []
    content {
      http_endpoint               = metadata_options.value.http_endpoint != "" ? metadata_options.value.http_endpoint : null
      http_tokens                 = metadata_options.value.http_tokens != "" ? metadata_options.value.http_tokens : null
      http_put_response_hop_limit = metadata_options.value.http_put_response_hop_limit
      instance_metadata_tags      = metadata_options.value.instance_metadata_tags != "" ? metadata_options.value.instance_metadata_tags : null
    }
  }
  dynamic "tag_specifications" {
    for_each = each.value.tag_specifications
    content {
      resource_type = tag_specifications.value.resource_type
      tags          = tag_specifications.value.tags
    }
  }
  # user-data OMITIDO de propósito (ver cabeçalho).
}
locals {
  # ID efetivo do LT por ID de origem (encontrado ou recém-criado).
  launch_template_id_by_source = {
    for k, cfg in var.launch_templates : k => try(
      aws_launch_template.this[k].id,
      data.external.lt_lookup[k].result.id,
      ""
    )
  }
  # Versão efetiva do LT por ID de origem.
  launch_template_version_by_source = {
    for k, cfg in var.launch_templates : k => try(
      tostring(aws_launch_template.this[k].latest_version),
      data.external.lt_lookup[k].result.default_version,
      ""
    )
  }
}
"""
