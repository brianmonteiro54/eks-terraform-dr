"""Orquestrador: captura o cluster EKS na origem e gera o Terraform modular
(.tf + terraform.auto.tfvars.json + scripts/aws_lookup.py + CLUSTER-INFO.md)."""
import base64
import json
import os
import re
import sys
from pathlib import Path

from .aws_cli import run_aws_command, _CAPTURE_FAILURES
from .helpers import _strip_nonportable_tags
from .access_entries import should_exclude_access_entry
from .collectors.iam import collect_iam_roles, _sanitize_trust_policy
from .collectors.network import collect_network
from .collectors.transit_gateway import collect_transit_gateways
from .collectors.security_groups import collect_security_groups, collect_cluster_sg_rules
from .collectors.launch_templates import collect_launch_templates
from .collectors.key_pairs import collect_key_pairs
from .terraform import TERRAFORM_FILES
from .report import write_cluster_info

# Caminho do helper real do data.external, copiado para scripts/aws_lookup.py na
# geração (substitui o antigo blob base64 embutido).
_LOOKUP_SRC = Path(__file__).resolve().parent / "lookup" / "aws_lookup.py"

def generate_modular_eks_terraform(cluster_name, region, profile, capture_full_vpc=True):
    """
    Gera uma estrutura de Terraform modular (baseada em tfvars)
    para um cluster EKS existente.
    """
    
    output_dir = Path(f"terraform-{cluster_name}")
    output_dir.mkdir(exist_ok=True)
    print(f"Gerando arquivos Terraform em: {output_dir.resolve()}")
    # Zera o registro de comandos AWS que falharam (preenchido por run_aws_command).
    _CAPTURE_FAILURES.clear()
    # 1. Escrever os arquivos HCL estáticos
    for filename, content in TERRAFORM_FILES.items():
        (output_dir / filename).write_text(content.strip())
    print(f"✓ Arquivos .tf modulares gerados com sucesso.")
    # 1.1 Escrever o helper do data.external (scripts/aws_lookup.py)
    # É o motor do find-or-create: consulta a conta de DESTINO via AWS CLI.
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    lookup_path = scripts_dir / "aws_lookup.py"
    lookup_path.write_bytes(_LOOKUP_SRC.read_bytes())
    os.chmod(lookup_path, 0o755)
    print(f"✓ Helper de lookup gerado em: scripts/aws_lookup.py")
    # 2. Coletar dados da AWS
    print("\nColetando dados do cluster EKS na AWS...")
    
    # -- Cluster --
    cluster_info = run_aws_command(f"aws eks describe-cluster --name {cluster_name} --region {region}", profile)
    if not cluster_info:
        print("Erro fatal: Não foi possível obter informações do cluster.", file=sys.stderr)
        return
    cluster = cluster_info['cluster']
    # -- Node Groups --
    node_groups = run_aws_command(f"aws eks list-nodegroups --cluster-name {cluster_name} --region {region}", profile)
    node_group_details = {}
    if node_groups and node_groups.get('nodegroups'):
        for ng_name in node_groups['nodegroups']:
            ng_info = run_aws_command(f"aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name {ng_name} --region {region}", profile)
            if ng_info:
                node_group_details[ng_name] = ng_info['nodegroup']
    # -- Fargate Profiles --
    fargate_profiles = run_aws_command(f"aws eks list-fargate-profiles --cluster-name {cluster_name} --region {region}", profile)
    fargate_profile_details = {}
    if fargate_profiles and fargate_profiles.get('fargateProfileNames'):
        for fp_name in fargate_profiles['fargateProfileNames']:
            fp_info = run_aws_command(f"aws eks describe-fargate-profile --cluster-name {cluster_name} --fargate-profile-name {fp_name} --region {region}", profile)
            if fp_info:
                fargate_profile_details[fp_name] = fp_info['fargateProfile']
    # -- Pod Identity Associations (COLETADO PRIMEIRO para resolver ARNs dos add-ons) --
    print("   → Pod Identity Associations: Coletando...")
    pod_identity_associations = run_aws_command(f"aws eks list-pod-identity-associations --cluster-name {cluster_name} --region {region}", profile)
    all_pod_identities = {}  # Todas as associações
    addon_association_ids = set()  # IDs que pertencem a add-ons
    
    if pod_identity_associations and pod_identity_associations.get('associations'):
        for assoc in pod_identity_associations['associations']:
            assoc_id = assoc['associationId']
            assoc_info = run_aws_command(f"aws eks describe-pod-identity-association --cluster-name {cluster_name} --association-id {assoc_id} --region {region}", profile)
            if assoc_info:
                all_pod_identities[assoc_id] = assoc_info['association']
                print(f"     Pod Identity encontrada: {assoc_info['association'].get('namespace')}/{assoc_info['association'].get('serviceAccount')}")
    print(f"   → Pod Identity Associations: {len(all_pod_identities)} encontrado(s)")
    # -- Add-ons (COM RESOLUÇÃO DE POD IDENTITY) --
    addons = run_aws_command(f"aws eks list-addons --cluster-name {cluster_name} --region {region}", profile)
    addon_details = {}
    if addons and addons.get('addons'):
        for addon_name in addons['addons']:
            addon_info = run_aws_command(f"aws eks describe-addon --cluster-name {cluster_name} --addon-name {addon_name} --region {region}", profile)
            if addon_info:
                addon = addon_info['addon']
                
                # NOVO: Resolver podIdentityAssociations do add-on
                raw_pia = addon.get('podIdentityAssociations', [])
                resolved_pia = []
                
                if raw_pia:
                    print(f"   → Add-on '{addon_name}' tem {len(raw_pia)} Pod Identity Association(s)")
                    
                    for pia_item in raw_pia:
                        role_arn = None
                        service_account = None
                        assoc_id_found = None
                        
                        # A API pode retornar:
                        # 1. Objeto com roleArn e serviceAccount
                        # 2. String com ARN da associação (formato observado)
                        if isinstance(pia_item, dict):
                            role_arn = pia_item.get('roleArn')
                            service_account = pia_item.get('serviceAccount')
                            
                            # Encontra o ID da associação correspondente
                            for assoc_id, assoc_data in all_pod_identities.items():
                                if (assoc_data.get('serviceAccount') == service_account and 
                                    assoc_data.get('roleArn') == role_arn):
                                    assoc_id_found = assoc_id
                                    break
                                    
                        elif isinstance(pia_item, str) and 'podidentityassociation' in pia_item:
                            # Formato: arn:aws:eks:REGION:ACCOUNT:podidentityassociation/CLUSTER/ASSOC_ID
                            assoc_id_found = pia_item.split('/')[-1]
                            
                            # Busca os detalhes no dicionário de associações já coletadas
                            if assoc_id_found in all_pod_identities:
                                assoc_data = all_pod_identities[assoc_id_found]
                                role_arn = assoc_data.get('roleArn')
                                service_account = assoc_data.get('serviceAccount')
                                print(f"     → Resolvido ARN: {service_account} → {role_arn}")
                            else:
                                print(f"     ⚠ AssociationId '{assoc_id_found}' não encontrado nas associações coletadas")
                                continue
                        else:
                            print(f"     ⚠ Formato não reconhecido de PIA: {type(pia_item)} - {pia_item}")
                            continue
                        
                        # Adiciona a associação resolvida
                        if role_arn and service_account:
                            resolved_pia.append({
                                'roleArn': role_arn,
                                'serviceAccount': service_account
                            })
                            
                            # Marca como pertencente ao add-on
                            if assoc_id_found:
                                addon_association_ids.add(assoc_id_found)
                                print(f"     → {service_account} vinculado ao add-on '{addon_name}'")
                
                addon['_pod_identity_associations'] = resolved_pia
                addon_details[addon_name] = addon
    # -- Access Entries & Policies --
    auth_mode = cluster.get('accessConfig', {}).get('authenticationMode', 'CONFIG_MAP')
    print(f"\n📋 Modo de autenticação detectado: {auth_mode}")
    
    access_entry_details = {}
    excluded_entries = []
    
    if auth_mode in ['API', 'API_AND_CONFIG_MAP']:
        print("   → Access Entries: Coletando...")
        access_entries = run_aws_command(f"aws eks list-access-entries --cluster-name {cluster_name} --region {region}", profile)
        if access_entries and access_entries.get('accessEntries'):
            for principal_arn in access_entries['accessEntries']:
                entry_info = run_aws_command(f"aws eks describe-access-entry --cluster-name {cluster_name} --principal-arn {principal_arn} --region {region}", profile)
                if entry_info:
                    entry = entry_info['accessEntry']
                    
                    # Verificar se deve ser excluído
                    should_exclude, reason = should_exclude_access_entry(entry)
                    if should_exclude:
                        excluded_entries.append({
                            'arn': principal_arn,
                            'type': entry.get('type'),
                            'reason': reason
                        })
                        continue
                    
                    # Buscar policies associadas
                    policies = run_aws_command(f"aws eks list-associated-access-policies --cluster-name {cluster_name} --principal-arn {principal_arn} --region {region}", profile)
                    policy_associations = []
                    if policies and policies.get('associatedAccessPolicies'):
                        for assoc in policies['associatedAccessPolicies']:
                            policy_associations.append({
                                "policy_arn": assoc['policyArn'],
                                "access_scope": {
                                    "type": assoc['accessScope']['type'],
                                    "namespaces": assoc['accessScope'].get('namespaces', [])
                                }
                            })
                    
                    entry['policy_associations'] = policy_associations
                    
                    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', principal_arn.split('/')[-1])
                    access_entry_details[safe_key] = entry
        
        total_entries = len(access_entry_details) + len(excluded_entries)
        print(f"   → Access Entries: {total_entries} encontrado(s) total")
        print(f"   → Access Entries incluídos no Terraform: {len(access_entry_details)}")
        print(f"   → Access Entries excluídos (automáticos): {len(excluded_entries)}")
        if excluded_entries:
            for excluded in excluded_entries:
                print(f"     • Excluído: {excluded['arn'].split('/')[-1]} (tipo: {excluded['type']}, motivo: {excluded['reason']})")
    else:
        print(f"   → Access Entries: Pulado (modo {auth_mode} usa aws-auth ConfigMap)")
    print("✓ Coleta de dados da AWS concluída.")
    # 3. Transformar dados e criar o arquivo .tfvars.json
    print("\nTransformando dados para o formato TFVARS...")
    
    # -- Variáveis Raiz --
    vpc_config = cluster.get('resourcesVpcConfig', {})
    logging_config = cluster.get('logging', {}).get('clusterLogging', [{}])[0].get('types', [])
    access_config = cluster.get('accessConfig', {})
    
    cluster_security_group_id = vpc_config.get('clusterSecurityGroupId')
    additional_security_group_ids = vpc_config.get('securityGroupIds', [])
    # -- EKS Auto Mode --
    # Os três componentes precisam estar todos habilitados (ou todos desabilitados).
    # 'auto_mode_enabled' só é True se os três estiverem em true.
    compute_config = cluster.get('computeConfig') or {}
    storage_config = cluster.get('storageConfig') or {}
    network_config = cluster.get('kubernetesNetworkConfig') or {}
    elb_config = network_config.get('elasticLoadBalancing') or {}
    block_storage_config = storage_config.get('blockStorage') or {}
    auto_mode_compute_enabled = compute_config.get('enabled', False)
    auto_mode_elb_enabled = elb_config.get('enabled', False)
    auto_mode_storage_enabled = block_storage_config.get('enabled', False)
    auto_mode_enabled = bool(auto_mode_compute_enabled and auto_mode_elb_enabled and auto_mode_storage_enabled)
    auto_mode_partial = (auto_mode_compute_enabled or auto_mode_elb_enabled or auto_mode_storage_enabled) and not auto_mode_enabled
    auto_mode_node_pools = compute_config.get('nodePools', []) or []
    auto_mode_node_role_arn = compute_config.get('nodeRoleArn')
    if auto_mode_enabled:
        print(f"   → EKS Auto Mode: ✅ HABILITADO (node pools: {', '.join(auto_mode_node_pools) or 'nenhum'})")
    elif auto_mode_partial:
        print(f"   → EKS Auto Mode: ⚠️  ESTADO PARCIAL/INCONSISTENTE "
              f"(compute={auto_mode_compute_enabled}, elb={auto_mode_elb_enabled}, storage={auto_mode_storage_enabled})")
    else:
        print(f"   → EKS Auto Mode: ❌ Desabilitado (cluster clássico)")
    
    # ATUALIZADO: Transformação de add-ons com pod_identity_associations
    addons_transformed = {}
    for addon_name, addon in addon_details.items():
        pod_identity_assocs = []
        for pia in addon.get('_pod_identity_associations', []):
            pod_identity_assocs.append({
                "role_arn": pia.get('roleArn'),
                "service_account": pia.get('serviceAccount')
            })
        
        addons_transformed[addon_name] = {
            "addon_version": addon.get('addonVersion'),
            "configuration_values": addon.get('configurationValues'),
            "resolve_conflicts": addon.get('resolveConflicts', 'OVERWRITE'),
            "service_account_role_arn": addon.get('serviceAccountRoleArn'),
            "pod_identity_associations": pod_identity_assocs,
            "tags": addon.get('tags', {})
        }
    
    # ATUALIZADO: Filtra pod_identities para incluir apenas as standalone
    standalone_pod_identities = {
        assoc_id: {
            "namespace": assoc.get('namespace'),
            "service_account": assoc.get('serviceAccount'),
            "role_arn": assoc.get('roleArn'),
            "tags": assoc.get('tags', {})
        }
        for assoc_id, assoc in all_pod_identities.items()
        if assoc_id not in addon_association_ids
    }
    # =================================================================
    # COLETA FIND-OR-CREATE: definições completas (rede, IAM, SGs) da
    # conta de ORIGEM, para permitir recriar tudo em outra conta.
    # =================================================================
    print("\n🔎 Coletando definições para portabilidade entre contas (find-or-create)...")
    vpc_id = vpc_config.get('vpcId')
    # Subnets referenciadas = cluster ∪ todos os nodegroups ∪ todos os fargate.
    referenced_subnet_ids = list(vpc_config.get('subnetIds', []) or [])
    for ng in node_group_details.values():
        referenced_subnet_ids += ng.get('subnets', []) or []
    for fp in fargate_profile_details.values():
        referenced_subnet_ids += fp.get('subnets', []) or []
    # Roles referenciadas: TODA role com ARN da conta de origem que aparece em
    # qualquer lugar do tfvars precisa ser recriada (find-or-create) no destino,
    # senão o apply referencia um ARN inexistente.
    #   - cluster role, node roles (nodegroups + auto-mode), fargate exec role;
    #   - role_arn de CADA pod identity association standalone;            (CRÍTICO)
    #   - role_arn de CADA pod identity association dentro de add-on;       (CRÍTICO)
    #   - service_account_role_arn de add-ons (IRSA legado, quando houver);
    #   - principal_arn de access entries QUE forem role (não user/federação).
    referenced_role_arns = []
    if cluster.get('roleArn'):
        referenced_role_arns.append(cluster.get('roleArn'))
    for ng in node_group_details.values():
        if ng.get('nodeRole'):
            referenced_role_arns.append(ng.get('nodeRole'))
    if auto_mode_enabled and auto_mode_node_role_arn:
        referenced_role_arns.append(auto_mode_node_role_arn)
    for fp in fargate_profile_details.values():
        if fp.get('podExecutionRoleArn'):
            referenced_role_arns.append(fp.get('podExecutionRoleArn'))
    # Pod identity associations standalone.
    for assoc in standalone_pod_identities.values():
        if assoc.get('role_arn'):
            referenced_role_arns.append(assoc['role_arn'])
    # Pod identity associations e IRSA dentro de add-ons.
    for addon in addons_transformed.values():
        for pia in addon.get('pod_identity_associations', []) or []:
            if pia.get('role_arn'):
                referenced_role_arns.append(pia['role_arn'])
        if addon.get('service_account_role_arn'):
            referenced_role_arns.append(addon['service_account_role_arn'])
    # Access entries cujo principal é uma IAM role (users são recriados à parte
    # via find-or-create, pois o principal precisa existir no destino para o
    # access entry funcionar; federação/SSO continua sendo só reescrita de conta).
    access_entry_role_principals = []
    iam_users_def = {}
    for entry in access_entry_details.values():
        parn = entry.get('principalArn') or ''
        if ':role/' in parn:
            referenced_role_arns.append(parn)
        elif ':user/' in parn:
            access_entry_role_principals.append(parn)
            after = parn.split(':user', 1)[1]  # "/NAME" ou "/path/NAME"
            uname = after.split('/')[-1]
            upath = after[:after.rfind('/') + 1] if '/' in after else '/'
            if uname and uname not in iam_users_def:
                iam_users_def[uname] = {"path": upath or "/"}
    # Account-id da conta de ORIGEM (para reescrever ARNs não-recriados no destino,
    # ex.: principal_arn de access entries que apontam para users/federação).
    source_account_id = ""
    for _arn in referenced_role_arns + access_entry_role_principals:
        m = re.match(r"arn:aws:iam::(\d+):", _arn or "")
        if m:
            source_account_id = m.group(1)
            break
    # SGs adicionais gerenciados = os SGs adicionais do cluster.
    referenced_sg_ids = list(additional_security_group_ids or [])
    # --- Launch Templates: coletados PRIMEIRO, pois descobrem SGs e roles
    # (instance profile) adicionais que precisam entrar na captura. ---
    print("   → Launch Templates (recriação automática)...")
    referenced_lts = {}  # id -> name
    for ng_name, ng in node_group_details.items():
        lt = ng.get('launchTemplate') or {}
        if lt.get('id'):
            referenced_lts[lt['id']] = lt.get('name', '')
    (launch_templates_def, lt_sg_source_ids, instance_profiles_def,
     lt_role_arns, lt_user_data, lt_warnings) = collect_launch_templates(
        referenced_lts, region, profile, run_aws_command)
    # Mescla as dependências dos LTs nos conjuntos de captura.
    # O Cluster SG do EKS NÃO é recriado (é gerenciado pelo EKS); ele será
    # remapeado para o SG do cluster novo dentro do launch_templates.tf.
    for s in lt_sg_source_ids:
        if s and s != cluster_security_group_id and s not in referenced_sg_ids:
            referenced_sg_ids.append(s)
    for r in lt_role_arns:
        if r and r not in referenced_role_arns:
            referenced_role_arns.append(r)
    # --- Key pairs EC2 (recriados no destino com a mesma chave pública) ---
    # Reúne os key_name dos LTs e o ec2SshKey de remote_access de nodegroups.
    print("   → Key pairs EC2 (recria a chave pública no destino)...")
    referenced_key_names = [lt.get("key_name") for lt in launch_templates_def.values()]
    for ng in node_group_details.values():
        ra = ng.get("remoteAccess") or {}
        if isinstance(ra, dict) and ra.get("ec2SshKey"):
            referenced_key_names.append(ra.get("ec2SshKey"))
    key_pairs_def, key_pair_warnings = collect_key_pairs(
        referenced_key_names, region, profile, run_aws_command)
    # LTs cujo key pair NÃO pôde ser recriado: remove o key_name (sobe sem SSH).
    _recreatable_keys = set(key_pairs_def.keys())
    for lt in launch_templates_def.values():
        if lt.get("key_name") and lt["key_name"] not in _recreatable_keys:
            lt["key_name"] = ""
    # --- Rede ---
    print("   → Rede (VPC/subnets/route tables)..." +
          ("  [VPC INTEIRA]" if capture_full_vpc else ""))
    net_info = collect_network(vpc_id, referenced_subnet_ids, region, profile, run_aws_command,
                               capture_full_vpc=capture_full_vpc) \
        if vpc_id else {
            "vpc": {}, "secondary_cidrs": [], "subnets": {}, "route_tables": {},
            "routes": [], "route_table_associations": [],
            "create_internet_gateway": False, "create_nat_gateways": False, "dropped_routes": [],
            "transit_gateway_attachments": {}, "gateway_endpoints": {}, "nat_gateways": {},
            "interface_endpoints": {}, "interface_endpoint_sg_ids": [], "dhcp_options": {},
            "orphan_nat_routes": [],
        }
    vpc_def = net_info.get("vpc", {}) or {}
    # SGs usados pelos interface endpoints entram na captura find-or-create
    # (para o endpoint referenciá-los no destino). O Cluster SG do EKS não é
    # recriado aqui (é gerenciado pelo EKS no destino, com OUTRO id).
    for s in net_info.get("interface_endpoint_sg_ids", []):
        if s and s != cluster_security_group_id and s not in referenced_sg_ids:
            referenced_sg_ids.append(s)
    # Se algum interface endpoint usa o Cluster SG da origem, ele é REMAPEADO no
    # HCL para o Cluster SG do cluster NOVO (que recebe as mesmas regras manuais
    # via cluster_sg_ingress/egress_rules + token __CLUSTER_SG__). O Cluster SG NÃO
    # entra no find-or-create (é gerenciado pelo EKS), mas continua na lista do
    # endpoint para o template religá-lo. Só registramos para informar no relatório.
    endpoint_cluster_sg_warnings = []
    if cluster_security_group_id:
        for eid, ep in net_info.get("interface_endpoints", {}).items():
            if cluster_security_group_id in ep.get("security_group_source_ids", []):
                endpoint_cluster_sg_warnings.append(eid)
    # --- IAM ---
    print("   → IAM roles (trust/managed/inline) e policies customer-managed...")
    iam_roles_def, customer_policies_def, iam_warnings = collect_iam_roles(
        referenced_role_arns, region, profile, run_aws_command)
    # Reescreve a conta de ORIGEM -> token __DEST_ACCOUNT__ nos documentos das
    # policies customer-managed (o Terraform troca pela conta de destino em apply).
    # Cobre auto-referências comuns dessas policies (ex.: iam:PassRole na node role,
    # ARNs de recursos da própria conta). ARNs de OUTRAS contas ficam intactos.
    if source_account_id:
        for pdef in customer_policies_def.values():
            doc = pdef.get("document", "")
            if source_account_id in doc:
                pdef["document"] = doc.replace(source_account_id, "__DEST_ACCOUNT__")
        # Mesma reescrita para as policies dos VPC gateway endpoints (S3/DynamoDB),
        # que podem referenciar ARNs com o account-id da origem (ex.: tabelas
        # DynamoDB arn:aws:dynamodb:regiao:CONTA:table/...). O Terraform troca
        # __DEST_ACCOUNT__ pela conta de destino em apply.
        for ep in net_info.get("gateway_endpoints", {}).values():
            pol = ep.get("policy", "")
            if pol and source_account_id in pol:
                ep["policy"] = pol.replace(source_account_id, "__DEST_ACCOUNT__")
        # Idem para os interface endpoints (ECR/STS/Logs/etc.): a policy pode
        # referenciar ARNs/condições com o account-id da origem.
        for ep in net_info.get("interface_endpoints", {}).values():
            pol = ep.get("policy", "")
            if pol and source_account_id in pol:
                ep["policy"] = pol.replace(source_account_id, "__DEST_ACCOUNT__")
    # --- Sanitiza as trust policies para portabilidade entre contas ---
    # Monta o conjunto de roles que são ALVO de Pod Identity (standalone + add-on):
    # essas recebem a trust de pods.eks.amazonaws.com (o OIDC/IRSA da origem é
    # vestigial e não portável). Demais roles têm a trust higienizada (remoção de
    # principals órfãos/OIDC, reescrita de conta origem→destino).
    pod_identity_role_names = set()
    for assoc in standalone_pod_identities.values():
        arn = assoc.get('role_arn')
        if arn:
            pod_identity_role_names.add(arn.split('/')[-1])
    for addon in addons_transformed.values():
        for pia in addon.get('pod_identity_associations', []) or []:
            arn = pia.get('role_arn')
            if arn:
                pod_identity_role_names.add(arn.split('/')[-1])
    trust_sanitize_notes = []
    captured_role_names = set(iam_roles_def.keys())
    for rname, rdef in iam_roles_def.items():
        sanitized, notes = _sanitize_trust_policy(
            rdef.get("assume_role_policy"),
            rname in pod_identity_role_names,
            source_account_id,
            captured_role_names,
        )
        rdef["assume_role_policy"] = sanitized
        if notes:
            trust_sanitize_notes.append(f"Role '{rname}': " + "; ".join(notes) + ".")
    # --- Security Groups adicionais ---
    print("   → Security Groups adicionais e regras...")
    sg_def, sg_ingress, sg_egress, sg_dropped = collect_security_groups(
        referenced_sg_ids, region, profile, run_aws_command,
        cluster_sg_id=cluster_security_group_id)
    # --- Regras manuais adicionadas ao Cluster SG (gerenciado pelo EKS) ---
    # O Cluster SG é criado pelo EKS, mas costuma receber regras manuais
    # (liberar VPC de peering, liberar o workers SG, etc.) que não vinham
    # sendo replicadas. São capturadas aqui e recriadas no Cluster SG novo.
    print("   → Regras manuais do Cluster SG do EKS...")
    cluster_sg_ingress, cluster_sg_egress, cluster_sg_dropped = collect_cluster_sg_rules(
        cluster_security_group_id, region, profile, run_aws_command, referenced_sg_ids)
    sg_dropped.extend(cluster_sg_dropped)
    net_dropped = net_info.get("dropped_routes", [])
    # --- Transit Gateways (config completa, p/ recriação cross-account) ---
    # Reúne os tgw-ids que aparecem em rotas (target_kind == "tgw") e nos
    # attachments capturados; captura a configuração de cada um para que, no
    # destino, se o TGW não existir (nem via RAM nem por Name tag), o Terraform
    # crie um novo idêntico ao da origem.
    print("   → Transit Gateways (config p/ replicação cross-account)...")
    _tgw_ids = []
    for r in net_info.get("routes", []):
        if r.get("target_kind") == "tgw" and r.get("target_id"):
            _tgw_ids.append(r["target_id"])
    for a in net_info.get("transit_gateway_attachments", {}).values():
        if a.get("transit_gateway_id"):
            _tgw_ids.append(a["transit_gateway_id"])
    transit_gateways_def, tgw_warnings = collect_transit_gateways(
        _tgw_ids, region, profile, run_aws_command)
    # --- Nota sobre access entries cujo principal é USER (agora recriado) ---
    ae_user_warnings = []
    for uname in iam_users_def:
        ae_user_warnings.append(
            f"IAM USER '{uname}' (referenciado por access entry) é **recriado** no "
            f"destino via find-or-create (user vazio, sem credenciais). O access entry "
            f"passa a apontar para ele. ⚠️ Adicione credenciais/console/SSO ao user no "
            f"destino para que a pessoa consiga autenticar."
        )
    # --- Tags apontando para recursos da conta de ORIGEM ---
    # Tags não-portáveis (awsApplication/AppRegistry e ARNs de resource-group) já
    # foram REMOVIDAS automaticamente em _tags_to_map/_strip_nonportable_tags. Aqui
    # só avisamos sobre OUTRAS tags que ainda referenciem a conta de origem (raras).
    tag_warnings = []
    def _scan_tags(tagmap, where):
        for tk, tv in _strip_nonportable_tags(tagmap or {}).items():
            if isinstance(tv, str) and source_account_id and source_account_id in tv:
                tag_warnings.append(
                    f"Tag `{tk}` em {where} ainda referencia a conta de origem "
                    f"(`{tv}`). Revise/ajuste no destino se necessário."
                )
    _scan_tags(cluster.get('tags'), "cluster")
    for ng_name, ng in node_group_details.items():
        _scan_tags(ng.get('tags'), f"nodegroup `{ng_name}`")
    for fp_name, fp in fargate_profile_details.items():
        _scan_tags(fp.get('tags'), f"fargate `{fp_name}`")
    print(f"   → find-or-create: {len(net_info.get('subnets', {}))} subnet(s), "
          f"{len(iam_roles_def)} role(s), {len(sg_def)} SG(s) adicional(is) capturado(s).")
    net_orphan_nat = net_info.get("orphan_nat_routes", [])
    if net_orphan_nat:
        _rts = sorted({o["route_table_source_id"] for o in net_orphan_nat})
        print(f"   ⚠️  ATENÇÃO: {len(net_orphan_nat)} rota(s) para NAT NÃO recriada(s) "
              f"em {len(_rts)} route table(s) — subnets podem ficar SEM internet. "
              f"Veja CLUSTER-INFO.md (NAT não capturado).")
    extra_warn = len(lt_warnings) + len(ae_user_warnings) + len(key_pair_warnings)
    if iam_warnings or sg_dropped or net_dropped or extra_warn:
        print(f"   ⚠️  {len(iam_warnings)} aviso(s) IAM, {len(sg_dropped)} regra(s) de SG "
              f"descartada(s), {len(net_dropped)} rota(s) não portável(is), "
              f"{len(referenced_lts)} launch template(s), {len(ae_user_warnings)} "
              f"user(s) em access entry. Veja CLUSTER-INFO.md.")
    # Salva o user-data original de cada LT (removido na recriação) como referência.
    if lt_user_data:
        ud_dir = output_dir / "launch-templates-userdata"
        ud_dir.mkdir(exist_ok=True)
        for lt_id, ud_b64 in lt_user_data.items():
            try:
                decoded = base64.b64decode(ud_b64).decode("utf-8", errors="replace")
            except Exception:
                decoded = ud_b64
            lt_label = launch_templates_def.get(lt_id, {}).get("name", lt_id)
            with open(ud_dir / f"{lt_label}.userdata.txt", "w") as f:
                f.write(decoded)
    # Endpoint de acesso do API server (reflete a origem; antes era fixo).
    endpoint_private = vpc_config.get('endpointPrivateAccess', True)
    endpoint_public = vpc_config.get('endpointPublicAccess', False)
    public_cidrs = vpc_config.get('publicAccessCidrs', []) or []
    # O EKS sempre devolve 0.0.0.0/0 como default; só o propagamos se o acesso
    # público estiver ligado e a lista for mais restritiva que o default.
    if not endpoint_public or public_cidrs == ["0.0.0.0/0"]:
        public_cidrs = []
    # Criptografia de secrets (KMS) na origem — a chave NÃO é portável.
    enc_cfg = cluster.get('encryptionConfig', []) or []
    cluster_encryption_enabled = False
    source_kms_key_arn = ""
    for ec in enc_cfg:
        if "secrets" in (ec.get('resources', []) or []):
            cluster_encryption_enabled = True
            source_kms_key_arn = (ec.get('provider', {}) or {}).get('keyArn', "")
    if cluster_encryption_enabled:
        iam_warnings.append(
            f"A ORIGEM criptografa secrets com KMS (chave `{source_kms_key_arn}`). "
            f"Essa chave não existe no destino. Informe `cluster_encryption_kms_key_arn` "
            f"com uma chave KMS da conta de destino, ou defina "
            f"`cluster_encryption_enabled = false` para abrir mão da criptografia. "
            f"O apply falha de propósito enquanto isso não for resolvido."
        )
    # Campos adicionais do tfvars (find-or-create).
    findcreate_tfvars = {
        # NOTA: aws_profile NÃO é gravado de propósito. O backup roda com o profile
        # da ORIGEM, mas o apply roda na conta de DESTINO. Gravar o profile da origem
        # faria os lookups (data.external) consultarem a conta errada. Fica no default
        # ("" = cadeia de credenciais padrão); no destino o usuário autentica como
        # preferir (variáveis de ambiente, profile próprio via -var, etc.).
        # Conta de origem (para reescrever ARNs de principals não recriados).
        "source_account_id": source_account_id,
        # Endpoint de acesso do API server
        "endpoint_private_access": bool(endpoint_private),
        "endpoint_public_access": bool(endpoint_public),
        "public_access_cidrs": public_cidrs,
        # Criptografia de secrets (KMS)
        "cluster_encryption_enabled": cluster_encryption_enabled,
        # NOTA: cluster_encryption_kms_key_arn NÃO é escrito aqui de propósito.
        # A chave do DESTINO só o usuário conhece, e escrevê-la (mesmo vazia)
        # faria este arquivo sobrescrever, por ordem lexical de carga, qualquer
        # valor informado em outro *.auto.tfvars. Fica no default ("") da variável;
        # a precondition do cluster cobra o valor quando a criptografia está ligada.
        # VPC
        "vpc_cidr": vpc_def.get("cidr"),
        "vpc_name": vpc_def.get("name", "eks-vpc"),
        "vpc_instance_tenancy": vpc_def.get("instance_tenancy", "default"),
        "vpc_enable_dns_support": vpc_def.get("enable_dns_support", True),
        "vpc_enable_dns_hostnames": vpc_def.get("enable_dns_hostnames", True),
        "vpc_tags": vpc_def.get("tags", {}),
        "vpc_secondary_cidrs": net_info.get("secondary_cidrs", []),
        "create_internet_gateway": net_info.get("create_internet_gateway", False),
        "create_nat_gateways": net_info.get("create_nat_gateways", False),
        # Subnets / roteamento
        "subnets": net_info.get("subnets", {}),
        "route_tables": net_info.get("route_tables", {}),
        "routes": net_info.get("routes", []),
        "route_table_associations": net_info.get("route_table_associations", []),
        "transit_gateway_attachments": {
            k: {kk: vv for kk, vv in v.items() if kk != "missing_subnets"}
            for k, v in net_info.get("transit_gateway_attachments", {}).items()
        },
        "transit_gateways": transit_gateways_def,
        "gateway_endpoints": net_info.get("gateway_endpoints", {}),
        "nat_gateways": net_info.get("nat_gateways", {}),
        "interface_endpoints": net_info.get("interface_endpoints", {}),
        "dhcp_options": net_info.get("dhcp_options", {}),
        # IAM
        "iam_roles": iam_roles_def,
        "customer_managed_policies": customer_policies_def,
        "iam_users": iam_users_def,
        # Launch templates (recriação automática) e seus instance profiles.
        "launch_templates": launch_templates_def,
        "instance_profiles": instance_profiles_def,
        "key_pairs": key_pairs_def,
        "source_cluster_security_group_id": cluster_security_group_id or "",
        # Security groups adicionais
        "security_groups": sg_def,
        "sg_ingress_rules": sg_ingress,
        "sg_egress_rules": sg_egress,
        # Regras manuais do Cluster SG (recriadas no Cluster SG do destino)
        "cluster_sg_ingress_rules": cluster_sg_ingress,
        "cluster_sg_egress_rules": cluster_sg_egress,
    }
    tfvars_data = {
        # >>> PREENCHA com o profile da AWS CLI da conta de DESTINO (onde você roda
        #     o terraform apply). Deixe "" para usar a cadeia padrão de credenciais
        #     (env vars / SSO / role do ambiente). NÃO use o profile da conta de
        #     ORIGEM aqui — os lookups consultariam a conta errada.
        "aws_profile": "",
        "region": region,
        # disable_resource_reuse (OPCIONAL/AVANÇADO): em geral deixe false.
        # A ferramenta agora é idempotente AUTOMATICAMENTE — ela marca tudo que
        # cria com a tag eks-importer:stack e os lookups ignoram o que tem essa
        # marca; então re-aplicar não destrói o que ela criou, e o que já existe
        # no destino é reaproveitado. Só mude para true se quiser FORÇAR gerenciar
        # tudo, ignorando os lookups (ex.: garantir que nada será reusado).
        "disable_resource_reuse": False,
        "cluster_name": cluster.get('name'),
        "cluster_role_arn": cluster.get('roleArn'),
        "vpc_id": vpc_config.get('vpcId'),
        "subnet_ids": vpc_config.get('subnetIds', []),
        "security_group_ids": additional_security_group_ids,
        "service_ipv4_cidr": cluster.get('kubernetesNetworkConfig', {}).get('serviceIpv4Cidr'),
        "cluster_version": cluster.get('version'),
        "enabled_cluster_log_types": logging_config,
        "support_type": cluster.get('upgradePolicy', {}).get('supportType', 'STANDARD'),
        "deletion_protection": cluster.get('deletionProtection', False),
        "cluster_tags": _strip_nonportable_tags(cluster.get('tags', {})),
        "authentication_mode": access_config.get('authenticationMode', 'API_AND_CONFIG_MAP'),
        "bootstrap_cluster_creator_admin_permissions": access_config.get('bootstrapClusterCreatorAdminPermissions', True),
        # -- EKS Auto Mode --
        "auto_mode_enabled": auto_mode_enabled,
        "auto_mode_node_pools": auto_mode_node_pools,
        "auto_mode_node_role_arn": auto_mode_node_role_arn,
        
        # -- Transformar Node Groups --
        "nodegroups": {
            ng_name: {
                "subnet_ids": ng.get('subnets', []),
                "node_role_arn": ng.get('nodeRole'),
                "scaling_min": ng.get('scalingConfig', {}).get('minSize'),
                "scaling_max": ng.get('scalingConfig', {}).get('maxSize'),
                "scaling_desired": ng.get('scalingConfig', {}).get('desiredSize'),
                "ami_type": ng.get('amiType'),
                "capacity_type": ng.get('capacityType'),
                "instance_types": ng.get('instanceTypes', []),
                "version": ng.get('version'),
                "release_version": ng.get('releaseVersion'),
                "labels": ng.get('labels', {}),
                "tags": _strip_nonportable_tags(ng.get("tags", {})),
                "disk_size": ng.get('diskSize'),
                "taints": [
                    {
                        "key": t.get('key'),
                        "value": t.get('value'),
                        "effect": t.get('effect'),
                    }
                    for t in (ng.get('taints', []) or [])
                ],
                "launch_template": {
                    "id": ng.get('launchTemplate', {}).get('id'),
                    "name": ng.get('launchTemplate', {}).get('name'),
                    "version": ng.get('launchTemplate', {}).get('version', '$Latest')
                }
            } for ng_name, ng in node_group_details.items()
        },
        
        # -- Transformar Fargate Profiles --
        "fargate_profiles": {
            fp_name: {
                "pod_execution_role_arn": fp.get('podExecutionRoleArn'),
                "subnet_ids": fp.get('subnets', []),
                "selectors": fp.get('selectors', []),
                "tags": _strip_nonportable_tags(fp.get("tags", {}))
            } for fp_name, fp in fargate_profile_details.items()
        },
        
        # -- Transformar Access Entries (apenas os não excluídos) --
        "access_entries": {
            key: {
                "principal_arn": entry.get('principalArn'),
                "kubernetes_groups": entry.get('kubernetesGroups', []),
                "type": entry.get('type'),
                "user_name": entry.get('username'),
                "tags": entry.get('tags', {}),
                "policy_associations": entry.get('policy_associations', [])
            } for key, entry in access_entry_details.items()
        },
        
        # -- Add-ons (ATUALIZADO com pod_identity_associations) --
        "addons": addons_transformed,
        
        # -- Pod Identity Associations (ATUALIZADO: apenas standalone) --
        "pod_identity_associations": standalone_pod_identities
    }
    # Mescla os campos da estratégia find-or-create (rede, IAM, SGs).
    tfvars_data.update(findcreate_tfvars)
    # Expõe recreate_external_routes no tfvars SÓ quando há alvos EXTERNOS
    # (TGW attachment, ou rotas para tgw/peering/vgw/eni/carrier/core-network),
    # para o usuário desligar facilmente em DR cross-account. O default (true)
    # serve à recuperação na MESMA conta; em OUTRA conta, troque para false.
    _external_kinds = {"tgw", "peering", "vgw", "eni", "carrier", "core_network"}
    _has_external = bool(net_info.get("transit_gateway_attachments")) or any(
        r.get("target_kind") in _external_kinds for r in net_info.get("routes", []))
    if _has_external:
        tfvars_data["recreate_external_routes"] = True
    # Reposiciona recreate_external_routes para logo ABAIXO de disable_resource_reuse
    # no JSON gerado (em vez de ficar no fim do arquivo), deixando as duas flags de
    # controle juntas e fáceis de achar/editar. dicts do Python preservam a ordem
    # de inserção, então reconstruímos o dict inserindo a chave logo após a âncora.
    if "recreate_external_routes" in tfvars_data and "disable_resource_reuse" in tfvars_data:
        _rer_val = tfvars_data.pop("recreate_external_routes")
        _reordered = {}
        for _k, _v in tfvars_data.items():
            _reordered[_k] = _v
            if _k == "disable_resource_reuse":
                _reordered["recreate_external_routes"] = _rer_val
        tfvars_data = _reordered
    # 4. Escrever o arquivo .tfvars.json
    tfvars_file = output_dir / "terraform.auto.tfvars.json"
    with open(tfvars_file, 'w') as f:
        json.dump(tfvars_data, f, indent=2)
    
    print(f"✓ Dados transformados e salvos em: {tfvars_file.name}")
    # 4.5. Criar arquivo de informações sobre o Cluster
    info_file = write_cluster_info(output_dir, dict(
        access_entry_details=access_entry_details,
        additional_security_group_ids=additional_security_group_ids,
        addon_association_ids=addon_association_ids,
        addon_details=addon_details,
        ae_user_warnings=ae_user_warnings,
        all_pod_identities=all_pod_identities,
        auth_mode=auth_mode,
        auto_mode_compute_enabled=auto_mode_compute_enabled,
        auto_mode_elb_enabled=auto_mode_elb_enabled,
        auto_mode_enabled=auto_mode_enabled,
        auto_mode_node_pools=auto_mode_node_pools,
        auto_mode_node_role_arn=auto_mode_node_role_arn,
        auto_mode_partial=auto_mode_partial,
        auto_mode_storage_enabled=auto_mode_storage_enabled,
        cluster=cluster,
        cluster_security_group_id=cluster_security_group_id,
        cluster_sg_egress=cluster_sg_egress,
        cluster_sg_ingress=cluster_sg_ingress,
        customer_policies_def=customer_policies_def,
        endpoint_cluster_sg_warnings=endpoint_cluster_sg_warnings,
        excluded_entries=excluded_entries,
        findcreate_tfvars=findcreate_tfvars,
        iam_roles_def=iam_roles_def,
        iam_warnings=iam_warnings,
        key_pair_warnings=key_pair_warnings,
        key_pairs_def=key_pairs_def,
        lt_warnings=lt_warnings,
        net_dropped=net_dropped,
        net_info=net_info,
        node_group_details=node_group_details,
        sg_dropped=sg_dropped,
        standalone_pod_identities=standalone_pod_identities,
        tag_warnings=tag_warnings,
        tgw_warnings=tgw_warnings,
        transit_gateways_def=transit_gateways_def,
        trust_sanitize_notes=trust_sanitize_notes,
        vpc_config=vpc_config,
        vpc_def=vpc_def,
        vpc_id=vpc_id,
    ))
    # Recomputados aqui para o resumo impresso abaixo (o relatório calcula os
    # seus próprios internamente; são contagens/filtros baratos).
    standalone_count = len(standalone_pod_identities)
    addon_count = len(addon_association_ids)
    addons_with_pia = {k: v for k, v in addon_details.items() if v.get('_pod_identity_associations')}
    print(f"✓ Informações do cluster salvas em: {info_file.name}")
    print("\n" + "="*80)
    print("📝 NOTAS IMPORTANTES:")
    print("="*80)
    print(f"1. 🔒 CLUSTER SECURITY GROUP:")
    print(f"   - O EKS criou automaticamente o SG: {cluster_security_group_id}")
    print(f"   - Este SG é GERENCIADO pelo EKS e NÃO PODE ser especificado no Terraform")
    print(f"   - Security Groups adicionais: {len(additional_security_group_ids)} configurado(s)")
    print(f"\n2. 🔐 MODO DE AUTENTICAÇÃO: {auth_mode}")
    if auth_mode == 'CONFIG_MAP':
        print(f"   - ⚠️  Usando aws-auth ConfigMap (modo legado)")
        print(f"   - Access Entries não disponíveis neste modo")
        print(f"   - Considere migrar para API_AND_CONFIG_MAP para usar Access Entries")
    else:
        total_entries = len(access_entry_details) + len(excluded_entries)
        print(f"   - ✅ Access Entries Total: {total_entries}")
        print(f"   - ✅ Access Entries incluídos no Terraform: {len(access_entry_details)}")
        print(f"   - ⚠️  Access Entries excluídos (automáticos): {len(excluded_entries)}")
        if excluded_entries:
            print(f"   - Os seguintes roles AUTOMÁTICOS foram excluídos e NÃO serão gerenciados:")
            for excluded in excluded_entries:
                print(f"     • {excluded['arn'].split('/')[-1]} ({excluded['type']})")
            print(f"   - Estes roles permanecem no cluster mas são gerenciados automaticamente pela AWS")
    
    print(f"\n3. 🎯 POD IDENTITY ASSOCIATIONS:")
    print(f"   - Total: {len(all_pod_identities)} associação(ões)")
    print(f"   - Vinculadas a Add-ons: {addon_count} (gerenciadas no aws_eks_addon)")
    print(f"   - Standalone: {standalone_count} (gerenciadas no aws_eks_pod_identity_association)")
    
    if addons_with_pia:
        print(f"\n   Add-ons com Pod Identity:")
        for addon_name, addon in addons_with_pia.items():
            for pia in addon.get('_pod_identity_associations', []):
                print(f"     • {addon_name} → {pia.get('serviceAccount')}")
    
    if standalone_pod_identities:
        print(f"\n   Pod Identity Standalone:")
        for assoc_id in standalone_pod_identities:
            assoc = all_pod_identities[assoc_id]
            print(f"     • {assoc.get('namespace')}/{assoc.get('serviceAccount')}")
    print(f"\n4. 🤖 EKS AUTO MODE: {'✅ HABILITADO' if auto_mode_enabled else ('⚠️  ESTADO INCONSISTENTE' if auto_mode_partial else '❌ Desabilitado')}")
    if auto_mode_enabled:
        print(f"   - Node Pools: {', '.join(auto_mode_node_pools) if auto_mode_node_pools else '(nenhum)'}")
        print(f"   - Node Role ARN: {auto_mode_node_role_arn}")
        print(f"   - ⚠️  O Node Role ARN é IMUTÁVEL após habilitar o Auto Mode")
        print(f"   - ⚠️  Auto Mode exige authentication_mode API ou API_AND_CONFIG_MAP (atual: {auth_mode})")
        print(f"   - compute/EBS/ELB e add-ons de rede (VPC CNI, CoreDNS, kube-proxy) são gerenciados pelo próprio EKS")
        if not node_group_details:
            print(f"   - Nenhum managed node group (esperado em cluster Auto Mode puro)")
    elif auto_mode_partial:
        print(f"   - ⚠️  ESTADO INCONSISTENTE: compute={auto_mode_compute_enabled}, elb={auto_mode_elb_enabled}, storage={auto_mode_storage_enabled}")
        print(f"   - Os três precisam estar TODOS habilitados ou TODOS desabilitados")
        print(f"   - O Terraform gerado assumiu Auto Mode = false. Revise manualmente antes de aplicar.")
    
    print("="*80)
    print(f"⚠️  ATENÇÃO: ESCOLHA O PROCEDIMENTO CORRETO")
    print("="*80)
    print(f"\n🌱 CRIAR UM NOVO CLUSTER (Do zero):")
    print(f"   - Caso queira subir uma infraestrutura nova com estas configurações:")
    print(f"   - Execute a ordem: terraform init → terraform plan → terraform apply")
