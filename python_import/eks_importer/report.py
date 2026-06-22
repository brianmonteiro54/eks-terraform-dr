"""Geração do relatório CLUSTER-INFO.md (resumo da captura, avisos e limitações).

Recebe um dicionário de contexto (`ctx`) com tudo que o gerador capturou/derivou.
O corpo é idêntico ao do gerador monolítico; apenas foi isolado aqui para separar
a apresentação (relatório) da orquestração (coleta/transformação).
"""
from datetime import datetime, timezone

from .aws_cli import _CAPTURE_FAILURES


def write_cluster_info(output_dir, ctx):
    """Escreve CLUSTER-INFO.md em output_dir e devolve o Path do arquivo."""
    access_entry_details = ctx["access_entry_details"]
    additional_security_group_ids = ctx["additional_security_group_ids"]
    addon_association_ids = ctx["addon_association_ids"]
    addon_details = ctx["addon_details"]
    ae_user_warnings = ctx["ae_user_warnings"]
    all_pod_identities = ctx["all_pod_identities"]
    auth_mode = ctx["auth_mode"]
    auto_mode_compute_enabled = ctx["auto_mode_compute_enabled"]
    auto_mode_elb_enabled = ctx["auto_mode_elb_enabled"]
    auto_mode_enabled = ctx["auto_mode_enabled"]
    auto_mode_node_pools = ctx["auto_mode_node_pools"]
    auto_mode_node_role_arn = ctx["auto_mode_node_role_arn"]
    auto_mode_partial = ctx["auto_mode_partial"]
    auto_mode_storage_enabled = ctx["auto_mode_storage_enabled"]
    cluster = ctx["cluster"]
    cluster_security_group_id = ctx["cluster_security_group_id"]
    cluster_sg_egress = ctx["cluster_sg_egress"]
    cluster_sg_ingress = ctx["cluster_sg_ingress"]
    customer_policies_def = ctx["customer_policies_def"]
    endpoint_cluster_sg_warnings = ctx["endpoint_cluster_sg_warnings"]
    excluded_entries = ctx["excluded_entries"]
    findcreate_tfvars = ctx["findcreate_tfvars"]
    iam_roles_def = ctx["iam_roles_def"]
    iam_warnings = ctx["iam_warnings"]
    key_pair_warnings = ctx["key_pair_warnings"]
    key_pairs_def = ctx["key_pairs_def"]
    lt_warnings = ctx["lt_warnings"]
    net_dropped = ctx["net_dropped"]
    net_info = ctx["net_info"]
    node_group_details = ctx["node_group_details"]
    sg_dropped = ctx["sg_dropped"]
    standalone_pod_identities = ctx["standalone_pod_identities"]
    tag_warnings = ctx["tag_warnings"]
    tgw_warnings = ctx["tgw_warnings"]
    transit_gateways_def = ctx["transit_gateways_def"]
    trust_sanitize_notes = ctx["trust_sanitize_notes"]
    vpc_config = ctx["vpc_config"]
    vpc_def = ctx["vpc_def"]
    vpc_id = ctx["vpc_id"]
    info_file = output_dir / "CLUSTER-INFO.md"
    # Contagem de pod identities
    standalone_count = len(standalone_pod_identities)
    addon_count = len(addon_association_ids)
    with open(info_file, 'w') as f:
        f.write("# Informações do Cluster EKS\n\n")
        f.write(f"## Cluster: {cluster.get('name')}\n")
        f.write(f"Gerado em: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
        # =============================================================
        # Portabilidade entre contas (find-or-create)
        # =============================================================
        f.write("### 🔁 Portabilidade entre contas (find-or-create)\n\n")
        f.write("Este Terraform foi gerado para ser **portável**: ao rodar `terraform apply` em\n")
        f.write("**qualquer conta**, para cada recurso de base ele primeiro **procura** se já existe\n")
        f.write("e, se não existir, **cria idêntico** ao original. A decisão acontece em tempo de\n")
        f.write("`plan`, via `data.external` chamando `scripts/aws_lookup.py` (que usa o AWS CLI).\n\n")
        f.write("**Chaves de busca:**\n")
        f.write("- **VPC:** pelo CIDR primário. Se já houver VPC com este CIDR, ela é reutilizada.\n")
        f.write("- **Subnets:** por (vpc-id + cidr-block).\n")
        f.write("- **Security Groups adicionais:** por (vpc-id + nome).\n")
        f.write("- **IAM Roles:** pelo nome (o ARN muda entre contas). Captura **todas** as roles\n")
        f.write("  referenciadas: cluster, nodegroups, fargate, **pod identity associations**\n")
        f.write("  (standalone e de add-ons) e principals de access entries que sejam role.\n")
        f.write("  Os ARNs de role embutidos em pod identity, add-ons e access entries são\n")
        f.write("  **reescritos automaticamente** para a conta de destino.\n")
        f.write("- **Policies customer-managed:** pelo nome. As policies não-AWS anexadas às\n")
        f.write("  roles são **recriadas** (find-or-create) com o mesmo documento.\n")
        f.write("- **Users IAM:** pelo nome. Users referenciados por access entries são\n")
        f.write("  **recriados** (find-or-create) vazios, para o principal existir no destino.\n\n")
        f.write(f"**VPC de origem:** `{vpc_id}` — **CIDR (chave):** `{vpc_def.get('cidr')}`\n")
        if net_info.get('secondary_cidrs'):
            f.write(f"- CIDRs secundários: {', '.join('`'+c+'`' for c in net_info['secondary_cidrs'])}\n")
        n_pub = sum(1 for s in net_info.get('subnets', {}).values() if s.get('is_public'))
        n_priv = len(net_info.get('subnets', {})) - n_pub
        f.write(f"- Subnets capturadas: **{len(net_info.get('subnets', {}))}** "
                f"({n_pub} pública(s), {n_priv} privada(s))\n")
        f.write(f"- IAM roles capturadas: **{len(iam_roles_def)}** "
                f"({', '.join('`'+n+'`' for n in iam_roles_def) or 'nenhuma'})\n")
        if customer_policies_def:
            f.write(f"- Policies customer-managed **recriadas** (find-or-create por nome): "
                    f"**{len(customer_policies_def)}** "
                    f"({', '.join('`'+n+'`' for n in customer_policies_def)})\n")
        f.write(f"- Internet Gateway recriado quando a VPC é nova: "
                f"**{'sim' if findcreate_tfvars.get('create_internet_gateway') else 'não'}**\n")
        f.write(f"- NAT Gateway recriado quando a VPC é nova: "
                f"**{'sim' if findcreate_tfvars.get('create_nat_gateways') else 'não'}** "
                f"(`create_nat_gateways`)\n\n")
        f.write("> **Premissa importante:** se a VPC já existir no destino (mesmo CIDR), assume-se\n")
        f.write("> que a malha de rede dela (route tables, IGW, NAT) **já existe** — então o\n")
        f.write("> Terraform **não recria roteamento**, apenas reutiliza a VPC e procura/garante as\n")
        f.write("> subnets e SGs. Quando a VPC **não** existe, tudo é criado do zero.\n\n")
        f.write("#### ⚠️ Pré-requisitos e limitações\n")
        f.write("- **Profile da conta de destino:** o `aws_profile` é a **primeira linha** do\n")
        f.write("  `terraform.auto.tfvars.json` (vem vazio). Preencha com o profile da AWS CLI\n")
        f.write("  da conta de **DESTINO**, ex.: `\"aws_profile\": \"meu-profile-destino\"`. Deixe `\"\"`\n")
        f.write("  para usar a cadeia padrão de credenciais (env vars / SSO / role do ambiente).\n")
        f.write("  Não precisa mexer em `variables.tf`.\n")
        f.write("- **AWS CLI é obrigatório** na máquina que roda `terraform apply` (os lookups\n")
        f.write("  `data.external` o utilizam) e deve estar autenticado na conta de **destino**.\n")
        f.write("- **Mesma região (DR):** os nomes de AZ são preservados. Para outra região,\n")
        f.write("  ajuste `availability_zone` das subnets no `terraform.auto.tfvars.json`.\n")
        f.write("- **NAT Gateway:** recriado **fiel à origem** (1 por 1). Se a origem tem 1 NAT\n")
        f.write("  por AZ, recria 1 por AZ (HA preservado). Gera **custo** por NAT; ponha\n")
        f.write("  `create_nat_gateways = false` para não recriar nenhum (DR enxuto).\n")
        f.write("- **Policies IAM customer-managed** referenciadas por roles **são recriadas**\n")
        f.write("  automaticamente (find-or-create por nome). O account-id da origem é\n")
        f.write("  reescrito para o destino no documento; ⚠️ ARNs de **recursos** dentro da\n")
        f.write("  policy (buckets S3, chaves KMS, etc.) podem apontar para recursos da origem\n")
        f.write("  — revise se necessário. Policies da AWS (`arn:aws:iam::aws:policy/...`) são\n")
        f.write("  globais e anexadas direto.\n")
        f.write("- **Launch Templates** usados por nodegroups **são recriados automaticamente**\n")
        f.write("  (find-or-create por nome): AMI, instance type, disco, metadata e tags são\n")
        f.write("  copiados; os security groups são remapeados (o Cluster SG do EKS vira o do\n")
        f.write("  cluster novo); o instance profile e sua role são recriados. O **user-data é\n")
        f.write("  removido** de propósito para o EKS gerar o bootstrap do cluster NOVO — o\n")
        f.write("  original fica salvo em `launch-templates-userdata/`. ⚠️ Se a AMI for **custom\n")
        f.write("  privada** da origem, ela não existe no destino: troque por uma AMI válida lá.\n")
        f.write("- **Roles de pod identity/IRSA**: a trust policy é **saneada automaticamente**\n")
        f.write("  para o destino (remove OIDC/SAML da origem e principals órfãos; garante a\n")
        f.write("  trust de Pod Identity). As **permissions** (inline + customer-managed) são\n")
        f.write("  recriadas; se apontarem para recursos específicos da origem (ex.: buckets S3),\n")
        f.write("  revise no destino.\n")
        f.write("- **Endpoint do API server** (`endpoint_private_access`/`endpoint_public_access`/\n")
        f.write("  `public_access_cidrs`) reflete a origem — não é mais fixo. Revise se o destino\n")
        f.write("  exigir configuração de acesso diferente.\n")
        f.write("- **Criptografia de secrets (KMS):** se a origem usava, o apply exige que você\n")
        f.write("  informe `cluster_encryption_kms_key_arn` (uma chave da conta de destino, pois a\n")
        f.write("  da origem não existe lá) ou desligue via `cluster_encryption_enabled = false`.\n")
        if iam_warnings:
            f.write("\n**Avisos de IAM:**\n")
            for w in iam_warnings:
                f.write(f"- {w}\n")
        if trust_sanitize_notes:
            f.write("\n**Trust policies saneadas para portabilidade** (feito automaticamente):\n")
            f.write("As trust policies (assume_role_policy) foram ajustadas para funcionar na "
                    "conta de destino: principals órfãos (de usuários deletados) e provedores "
                    "OIDC/SAML da origem foram removidos, ARNs de conta foram reescritos para o "
                    "destino, e roles de Pod Identity receberam a trust `pods.eks.amazonaws.com`. "
                    "Se alguma role dependia de IRSA e ainda NÃO foi migrada para Pod Identity, "
                    "associe-a via Pod Identity (a trust já está pronta).\n")
            for w in trust_sanitize_notes:
                f.write(f"- {w}\n")
        if sg_dropped:
            f.write("\n**Regras de Security Group descartadas** (referenciavam um SG criado em "
                    "runtime pelo Load Balancer Controller, que não existe no apply e é recriado "
                    "pelo próprio controller no destino):\n")
            for d in sg_dropped:
                f.write(f"- SG `{d['sg']}` [{d['direction']}] → `{d['referenced']}` ({d['reason']})\n")
        if cluster_sg_ingress or cluster_sg_egress:
            f.write("\n**Regras manuais do Cluster SG do EKS recriadas** "
                    f"({len(cluster_sg_ingress)} ingress, {len(cluster_sg_egress)} egress):\n")
            f.write("O Cluster SG é criado pelo próprio EKS, mas recebeu regras manuais na origem. "
                    "Elas são recriadas no Cluster SG do cluster de destino (cujo ID o EKS gera). "
                    "As regras default do EKS (self/all-traffic) não são recriadas (o EKS as cria "
                    "sozinho). Referências ao workers SG e ao próprio Cluster SG são religadas ao "
                    "destino automaticamente.\n")
        if net_dropped:
            f.write("\n**Rotas apenas documentadas** (não viram `aws_route`):\n")
            f.write("Gateway endpoints (vpce-) são recriados pelo próprio `aws_vpc_endpoint`, e "
                    "alvos desconhecidos não são recriados.\n")
            for d in net_dropped:
                f.write(f"- route table `{d['route_table']}` → `{d['destination']}` ({d['reason']})\n")
        # AVISO CRÍTICO: rotas que apontavam para um NAT não capturado serão puladas.
        net_orphan_nat = net_info.get("orphan_nat_routes", [])
        if net_orphan_nat:
            f.write("\n**⚠️ Rotas para NAT não recriadas** — ATENÇÃO, pode deixar subnets sem internet:\n")
            f.write("Estas rotas apontavam, na origem, para um NAT Gateway que **não foi capturado** "
                    "(o NAT foi deletado e a rota virou blackhole, é um NAT privado, ou está numa subnet "
                    "fora do escopo). Como o NAT não existe no backup, a ferramenta **não recria estas "
                    "rotas**, e as subnets associadas ficarão **sem essa saída** (tipicamente sem rota "
                    "default para a internet):\n")
            for o in net_orphan_nat:
                f.write(f"- route table `{o['route_table_source_id']}` → `{o['destination']}` "
                        f"(apontava para `{o['nat_id']}`)\n")
            f.write("**Impacto:** se essas subnets hospedam nós do cluster (incluindo nós Auto Mode/"
                    "Fargate), eles podem ficar **sem acesso ao ECR** e não conseguir puxar imagens. "
                    "Antes de aplicar, decida a saída dessas subnets: crie um NAT novo e aponte a rota, "
                    "use os interface endpoints adequados (ECR/S3), ou ajuste o roteamento para o "
                    "ambiente de destino.\n")
        # Rotas para alvos externos: TGW e (agora) peering/VGW são resolvidos no
        # destino (find-or-skip); ENI é sempre pulada; carrier/core_network seguem
        # como ID literal (best-effort, nichos).
        _routes = net_info.get("routes", [])
        _peer_routes = [r for r in _routes if r.get("target_kind") == "peering"]
        _vgw_routes = [r for r in _routes if r.get("target_kind") == "vgw"]
        _carrier_routes = [r for r in _routes if r.get("target_kind") == "carrier"]
        _eni_routes = [r for r in _routes if r.get("target_kind") == "eni"]
        _lit_routes = [r for r in _routes if r.get("target_kind") == "core_network"]

        def _rdest(r):
            return (r.get("destination_cidr_block") or r.get("destination_ipv6_cidr_block")
                    or r.get("destination_prefix_list_id") or "?")

        if _peer_routes or _vgw_routes or _carrier_routes:
            f.write("\n**Rotas para peering / VPN Gateway / carrier (find-or-skip)** — resolvidas no destino:\n")
            f.write("Estas rotas NÃO usam mais o ID literal da origem. No `terraform plan`, o lookup "
                    "procura o equivalente na conta de DESTINO (peering ativa que cubra o CIDR da rota; "
                    "VGW anexado à VPC; carrier gateway da VPC). Se ACHAR, a rota aponta para o recurso do "
                    "destino; se NÃO achar, a rota é **pulada** (sem falhar o apply). Por isso funciona "
                    "cross-account. Crie/aceite o peering ou anexe o VGW/carrier no destino para "
                    "materializar a rota.\n")
            for r in _peer_routes:
                f.write(f"- peering -> destino `{_rdest(r)}` (route table `{r.get('route_table_source_id')}`)\n")
            for r in _vgw_routes:
                f.write(f"- VGW -> destino `{_rdest(r)}` (route table `{r.get('route_table_source_id')}`)\n")
            for r in _carrier_routes:
                f.write(f"- carrier -> destino `{_rdest(r)}` (route table `{r.get('route_table_source_id')}`)\n")
        if _eni_routes:
            f.write("\n**Rotas para ENI (sempre puladas)** — recriação manual só se for appliance seu:\n")
            f.write("A rota aponta para uma interface de rede (ENI) de um appliance/LB que esta stack não "
                    "gerencia, então é **sempre pulada**. Tipicamente a ENI pertence a um **Load Balancer** "
                    "provisionado pelo AWS Load Balancer Controller (requester `amazon-elb`): essas ENIs são "
                    "**recriadas pelo próprio controller** quando o ingress sobe e **não precisam de rota "
                    "estática**. Se a rota era para um appliance seu (firewall/NAT instance), recrie-o no "
                    "destino e adicione a rota manualmente:\n")
            for r in _eni_routes:
                f.write(f"- ENI `{r.get('target_id')}` -> destino `{_rdest(r)}` "
                        f"(route table `{r.get('route_table_source_id')}`)\n")
        if _lit_routes:
            f.write("\n**Rotas para core network / Cloud WAN (ID literal)** — revise:\n")
            f.write("A rota usa o **ARN literal** do core network da origem. Quando o core network está "
                    "**compartilhado via AWS RAM**, o mesmo ARN vale no destino e a rota funciona; se NÃO "
                    "estiver compartilhado com a conta de destino, o apply falha nessa rota. Compartilhe o "
                    "core network ou remova a rota do tfvars:\n")
            for r in _lit_routes:
                f.write(f"- core_network `{r.get('target_id')}` -> destino `{_rdest(r)}`\n")
        net_tgwa = net_info.get("transit_gateway_attachments", {})
        if net_tgwa or transit_gateways_def:
            f.write("\n**Transit Gateway — replicação cross-account (find-or-create)**\n")
            f.write("As rotas `-> tgw-xxx` e o attachment da VPC funcionam em **qualquer conta**. "
                    "Ao aplicar com `recreate_external_routes = true`, para cada TGW o lookup tenta, "
                    "em cascata: **(1)** mesmo ID visível via **AWS RAM** → usa direto; **(2)** mesmo "
                    "**Name tag** na conta de destino → usa o TGW existente; **(3)** não encontrado → "
                    "o Terraform **cria um TGW novo** com a mesma configuração da origem (ASN, "
                    "dns_support, vpn_ecmp_support, etc.) e o attachment/rotas passam a usar o ID "
                    "resolvido. Por isso **não é mais preciso** desligar `recreate_external_routes` em "
                    "DR cross-account por causa do TGW. (Em DR para conta nova e vazia, deixe `true`.)\n")
            if net_tgwa:
                f.write("\n_Attachments da VPC ao TGW (reanexados quando a VPC é nova):_\n")
                for aid, a in net_tgwa.items():
                    f.write(f"- `{aid}` → TGW de origem `{a['transit_gateway_id']}` "
                            f"(subnets: {', '.join('`'+s+'`' for s in a['subnet_source_ids']) or '—'})\n")
                    if a.get("missing_subnets"):
                        f.write(f"  - ⚠️ subnets do attachment NÃO capturadas: "
                                f"{', '.join('`'+s+'`' for s in a['missing_subnets'])}. "
                                f"Capture a VPC inteira (padrão; não use --cluster-subnets-only), senão o attachment fica incompleto.\n")
            if transit_gateways_def:
                f.write("\n_Configuração de TGW capturada (recriada se não existir no destino):_\n")
                for tid, t in transit_gateways_def.items():
                    n_rt = len(t.get("route_tables", {}))
                    n_sr = sum(len(rt.get("static_routes", [])) for rt in t.get("route_tables", {}).values())
                    f.write(f"- `{tid}` (Name `{t.get('name')}`): ASN `{t.get('amazon_side_asn')}`, "
                            f"dns_support `{t.get('dns_support')}`, vpn_ecmp `{t.get('vpn_ecmp_support')}`"
                            + (f", {n_rt} route table(s) customizada(s) / {n_sr} rota(s) estática(s) blackhole" if n_rt else "")
                            + "\n")
            f.write("\n⚠️ **Limitações da replicação de TGW (revise se aplicável):**\n")
            f.write("- Quando o TGW é **criado novo**, o attachment da VPC usa a **default route "
                    "table** do TGW (associação e propagação ligadas por padrão), o que cobre o caso "
                    "de **uma única VPC**. **Associações/propagações** customizadas de route table "
                    "**não são recriadas** automaticamente.\n")
            f.write("- **Outros attachments** do TGW de origem (outras VPCs, **VPN**, **Direct "
                    "Connect**, peering de TGW) **não são recriados** — só o attachment desta VPC. "
                    "Recrie os demais conforme o ambiente de destino.\n")
            f.write("- **Rotas estáticas** das route tables customizadas: só as **blackhole** são "
                    "recriadas (as que apontam para um attachment dependem de um alvo que a ferramenta "
                    "não resolve). Rotas **propagadas** (BGP) reaparecem sozinhas após os attachments.\n")
            f.write("- Se o TGW for **encontrado** no destino (via RAM ou Name tag), ele é **reutilizado "
                    "como está** — a ferramenta não altera a configuração nem as route tables dele.\n")
            if tgw_warnings:
                f.write("\n_Avisos da captura de TGW:_\n")
                for w in tgw_warnings:
                    f.write(f"- {w}\n")
        net_eps = net_info.get("gateway_endpoints", {})
        if net_eps:
            f.write("\n**VPC Gateway Endpoints recriados** (S3/DynamoDB; recriam as rotas por prefix-list):\n")
            for eid, e in net_eps.items():
                f.write(f"- `{eid}` → `{e['service_name']}` "
                        f"(route tables: {', '.join('`'+r+'`' for r in e['route_table_source_ids']) or '—'})\n")
        net_ifeps = net_info.get("interface_endpoints", {})
        if net_ifeps:
            f.write("\n**VPC Interface Endpoints recriados** (ECR/STS/Logs/etc. — vitais em VPC privada):\n")
            f.write("Sem eles, o cluster privado **não puxa imagens do ECR** e trava. Subnets e SGs são "
                    "remapeados para o destino (os SGs entram no find-or-create); `private_dns_enabled` "
                    "preservado da origem.\n")
            for eid, e in net_ifeps.items():
                sgs = ', '.join('`'+s+'`' for s in e['security_group_source_ids']) or '—'
                f.write(f"- `{eid}` → `{e['service_name']}` "
                        f"(private DNS: {'on' if e['private_dns_enabled'] else 'off'}, SGs: {sgs})\n")
                if not e['subnet_source_ids']:
                    f.write("  - ⚠️ sem subnets capturadas — será PULADO. Capture a VPC inteira (padrão).\n")
            if endpoint_cluster_sg_warnings:
                f.write("  - ℹ️ Estes endpoints usam o **Cluster SG** da origem; ele é religado "
                        "automaticamente ao **Cluster SG do cluster novo** (que recebe as mesmas "
                        "regras manuais via `cluster_sg_ingress_rules`/`cluster_sg_egress_rules`): "
                        f"{', '.join('`'+e+'`' for e in endpoint_cluster_sg_warnings)}. "
                        "Por isso, esses endpoints dependem do cluster e são criados após ele "
                        "(sem impacto: os nós que usam os endpoints sobem depois do cluster).\n")
        net_nats = net_info.get("nat_gateways", {})
        if net_nats:
            _n_reg = sum(1 for v in net_nats.values() if v.get("availability_mode") == "regional")
            _n_zon = len(net_nats) - _n_reg
            f.write(f"\n**NAT Gateways recriados FIEL à origem** ({len(net_nats)} NAT(s): "
                    f"{_n_zon} zonal, {_n_reg} regional):\n")
            f.write("Cada rota privada aponta para o NAT correto (pelo nat-id de origem). "
                    "NAT **zonal** é recriado 1-por-subnet como na origem (se há 1 por AZ, recria 1 por "
                    "AZ — HA preservado) e cada um ganha um EIP **novo** (se algum IP de saída é "
                    "whitelistado externamente, atualize a allowlist). NAT **regional** "
                    "(`availability_mode=regional`, comum com EKS Auto Mode) é recriado multi-AZ em "
                    "**auto mode** — a própria AWS provisiona e gerencia os EIPs e expande pelas AZs; "
                    "os IPs de saída serão novos.\n")
        net_dhcp = net_info.get("dhcp_options", {})
        if net_dhcp:
            f.write("\n**DHCP options set customizado recriado** (DNS on-prem/NTP/NetBIOS):\n")
            f.write("A VPC nova é associada a um conjunto de opções DHCP idêntico ao da origem, "
                    "preservando a resolução de nomes (ex.: DNS corporativo via TGW). O default da "
                    "região **não** é recriado (a VPC nova já o recebe).\n")
            for did, d in net_dhcp.items():
                parts = []
                if d.get("domain_name"):
                    parts.append(f"domain `{d['domain_name']}`")
                if d.get("domain_name_servers"):
                    parts.append(f"DNS {', '.join('`'+s+'`' for s in d['domain_name_servers'])}")
                if d.get("ntp_servers"):
                    parts.append(f"NTP {', '.join('`'+s+'`' for s in d['ntp_servers'])}")
                f.write(f"- `{did}`: {'; '.join(parts) or '(opções customizadas)'}\n")
        if lt_warnings:
            f.write("\n**Launch Templates** (recriados automaticamente — pontos de atenção):\n")
            for w in lt_warnings:
                f.write(f"- {w}\n")
        if key_pairs_def:
            f.write("\n**Key pairs EC2 recriados** (find-or-create por nome, mesma chave pública):\n")
            f.write("Os key pairs abaixo são recriados no destino com a **mesma chave pública** da "
                    "origem, então a **chave privada que você já tem continua válida** para SSH "
                    "(a privada nunca passa pela ferramenta).\n")
            for kpn in key_pairs_def:
                f.write(f"- `{kpn}`\n")
        if key_pair_warnings:
            f.write("\n**Key pairs EC2 não recriados** (key_name removido do LT):\n")
            for w in key_pair_warnings:
                f.write(f"- {w}\n")
        if ae_user_warnings:
            f.write("\n**Users IAM em access entries** (recriados via find-or-create):\n")
            for w in ae_user_warnings:
                f.write(f"- {w}\n")
        if tag_warnings:
            f.write("\n**Tags apontando para a conta de origem** (copiadas literalmente — revise):\n")
            for w in tag_warnings:
                f.write(f"- {w}\n")
        f.write("\n---\n\n")
        f.write("### Security Groups\n\n")
        f.write("**IMPORTANTE:** O EKS cria automaticamente um Security Group gerenciado (Cluster Security Group).\n")
        f.write("Este SG NÃO PODE ser especificado no Terraform - ele é gerenciado automaticamente pelo EKS.\n\n")
        f.write(f"**Cluster Security Group ID (auto-gerenciado):** `{cluster_security_group_id}`\n")
        if additional_security_group_ids:
            f.write(f"\n**Security Groups Adicionais (gerenciados por você):**\n")
            for sg in additional_security_group_ids:
                f.write(f"- `{sg}`\n")
        else:
            f.write("\n**Nenhum Security Group adicional configurado.**\n")
        # --- EKS Auto Mode ---
        f.write("\n### EKS Auto Mode\n")
        if auto_mode_enabled:
            f.write("- **Status:** ✅ Habilitado\n")
            f.write(f"- **Node Pools:** {', '.join(auto_mode_node_pools) if auto_mode_node_pools else '(nenhum)'}\n")
            f.write(f"- **Node Role ARN:** `{auto_mode_node_role_arn}`\n")
            f.write("- ⚠️  **O Node Role ARN é IMUTÁVEL** após o Auto Mode ser habilitado.\n")
            f.write("- Compute (EC2 Managed Instances), storage (EBS) e load balancing (ELB) são gerenciados automaticamente pelo EKS.\n")
            f.write("- Os add-ons de rede (VPC CNI, CoreDNS, kube-proxy) são gerenciados off-cluster pelo Auto Mode (`bootstrap_self_managed_addons = false`).\n")
            f.write(f"- Auto Mode exige `authentication_mode` = API ou API_AND_CONFIG_MAP (atual: **{auth_mode}**).\n")
            if not node_group_details:
                f.write("- Nenhum managed node group encontrado (esperado em um cluster Auto Mode puro).\n")
            else:
                f.write(f"- ⚠️  Foram encontrados {len(node_group_details)} managed node group(s) coexistindo com o Auto Mode (cluster híbrido).\n")
        elif auto_mode_partial:
            f.write("- **Status:** ⚠️  ESTADO INCONSISTENTE\n")
            f.write("- Nem todos os três componentes do Auto Mode estão habilitados:\n")
            f.write(f"  - compute_config: `{auto_mode_compute_enabled}`\n")
            f.write(f"  - elastic_load_balancing: `{auto_mode_elb_enabled}`\n")
            f.write(f"  - block_storage: `{auto_mode_storage_enabled}`\n")
            f.write("- O Terraform gerado tratou o Auto Mode como **desabilitado**. Revise manualmente.\n")
        else:
            f.write("- **Status:** ❌ Desabilitado (cluster clássico)\n")
            f.write("- Compute é gerenciado via managed node groups / Fargate / self-managed.\n")
        
        f.write("\n### Autenticação\n")
        f.write(f"- **Modo:** {auth_mode}\n")
        if auth_mode == 'CONFIG_MAP':
            f.write("- ⚠️  **Modo Legado:** Usa aws-auth ConfigMap para gerenciar acesso\n")
            f.write("- **Access Entries:** Não disponível neste modo\n")
            f.write("- **Recomendação:** Considere migrar para `API_AND_CONFIG_MAP`\n")
        else:
            total_entries = len(access_entry_details) + len(excluded_entries)
            f.write(f"- **Access Entries Total:** {total_entries}\n")
            f.write(f"- **Access Entries gerenciados pelo Terraform:** {len(access_entry_details)}\n")
            f.write(f"- **Access Entries excluídos (automáticos/sistema):** {len(excluded_entries)}\n")
            if excluded_entries:
                f.write("\n**Entries Excluídos (não gerenciados pelo Terraform):**\n")
                for excluded in excluded_entries:
                    f.write(f"- `{excluded['arn'].split('/')[-1]}` (tipo: {excluded['type']})\n")
                f.write("\n*Estes access entries são automáticos/de sistema e permanecem no cluster, mas não são gerenciados pelo Terraform.*\n")
        
        # ATUALIZADO: Seção de Pod Identity mais detalhada
        f.write("\n### Pod Identity Associations\n")
        f.write(f"- **Total:** {len(all_pod_identities)} associação(ões)\n")
        f.write(f"- **Vinculadas a Add-ons:** {addon_count} (gerenciadas pelo recurso aws_eks_addon)\n")
        f.write(f"- **Standalone:** {standalone_count} (gerenciadas pelo recurso aws_eks_pod_identity_association)\n")
        
        # Add-ons com Pod Identity
        addons_with_pia = {k: v for k, v in addon_details.items() if v.get('_pod_identity_associations')}
        if addons_with_pia:
            f.write("\n**Add-ons com Pod Identity:**\n")
            for addon_name, addon in addons_with_pia.items():
                for pia in addon.get('_pod_identity_associations', []):
                    f.write(f"- `{addon_name}` → `{pia.get('serviceAccount')}` → `{pia.get('roleArn')}`\n")
        
        # Standalone
        if standalone_pod_identities:
            f.write("\n**Pod Identity Standalone:**\n")
            for assoc_id in standalone_pod_identities:
                assoc = all_pod_identities[assoc_id]
                f.write(f"- `{assoc.get('namespace')}/{assoc.get('serviceAccount')}` → `{assoc.get('roleArn')}`\n")
        
        f.write("\n### Endpoints\n")
        f.write(f"- **Private Access:** {vpc_config.get('endpointPrivateAccess', False)}\n")
        f.write(f"- **Public Access:** {vpc_config.get('endpointPublicAccess', True)}\n")
        
        f.write(f"\n### Versão do Kubernetes\n")
        f.write(f"- {cluster.get('version')}\n")
        if _CAPTURE_FAILURES:
            f.write("\n---\n\n### ⚠️ Comandos AWS que falharam na captura\n")
            f.write("Estes comandos falharam ao ler a conta de ORIGEM — normalmente é **permissão "
                    "IAM faltando**. O backup pode estar **incompleto** (recursos não capturados). "
                    "Conceda as permissões `Describe*`/`Get*`/`List*` correspondentes e rode de novo:\n")
            seen = set()
            for cmd, err in _CAPTURE_FAILURES:
                if cmd in seen:
                    continue
                seen.add(cmd)
                f.write(f"- `{cmd}`" + (f" — {err}" if err else "") + "\n")
    
    return info_file
